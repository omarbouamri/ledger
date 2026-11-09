"""Outbound email: template rendering, validation, SMTP delivery, logging.

Safety posture
--------------
* ``JOBSCOUT_MAIL_DRY_RUN`` defaults to **on**. Nothing leaves the machine; the
  send is recorded with status ``simulated`` so the whole flow is testable.
* A per-user daily cap (``JOBSCOUT_MAIL_DAILY_CAP``) is enforced before the
  socket is opened.
* Headers are built with :mod:`email.message`, which encodes and folds them —
  no hand-built header strings, so a newline in a subject cannot inject a
  header.
* Recipients are validated and de-duplicated before anything is sent.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Iterable, Mapping, Sequence

from config import settings
from jobscout import repo

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s,;:<>\"]+@[^@\s,;:<>\"]+\.[A-Za-z]{2,}$")

# Placeholders a template may use. Anything else is left untouched.
PLACEHOLDERS = (
    "name",
    "sector",
    "address",
    "phone",
    "website",
    "rating",
    "reviews",
    "score",
    "contact_name",
    "sender_name",
    "city",
)


def valid_email(addr: str) -> bool:
    addr = (addr or "").strip()
    return bool(addr) and len(addr) <= 254 and _EMAIL_RE.match(addr) is not None


def clean_recipients(raw: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split an iterable of addresses into (valid, rejected), de-duplicated."""
    seen: set[str] = set()
    good: list[str] = []
    bad: list[str] = []
    for item in raw:
        for part in re.split(r"[,;\s]+", str(item or "")):
            addr = part.strip()
            if not addr:
                continue
            key = addr.casefold()
            if key in seen:
                continue
            seen.add(key)
            (good if valid_email(addr) else bad).append(addr)
    return good, bad


def render(text: str, emp: Mapping[str, Any], *, sender_name: str = "", contact_name: str = "") -> str:
    """Substitute ``{placeholder}`` tokens without choking on stray braces."""
    rating = emp.get("rating")
    reviews = emp.get("reviews")
    values = {
        "name": emp.get("name") or "your business",
        "sector": emp.get("sector") or "your field",
        "address": emp.get("address") or "",
        "phone": emp.get("phone") or "",
        "website": emp.get("website") or "",
        "rating": f"{float(rating):.1f}" if rating is not None else "unrated",
        "reviews": str(int(reviews)) if reviews else "0",
        "score": str(emp.get("score", "")),
        "contact_name": (contact_name or "").strip() or "there",
        "sender_name": (sender_name or "").strip() or "—",
        "city": settings.CITY.split(",")[0],
    }
    out = text or ""
    for key in PLACEHOLDERS:
        out = out.replace("{" + key + "}", values.get(key, ""))
    return out


@dataclass(slots=True)
class SendReport:
    sent: int = 0
    simulated: int = 0
    failed: int = 0
    skipped: int = 0
    messages: list[str] = field(default_factory=list)

    @property
    def delivered(self) -> int:
        return self.sent + self.simulated

    def summary(self) -> str:
        bits = []
        if self.sent:
            bits.append(f"{self.sent} sent")
        if self.simulated:
            bits.append(f"{self.simulated} simulated (dry run)")
        if self.failed:
            bits.append(f"{self.failed} failed")
        if self.skipped:
            bits.append(f"{self.skipped} skipped")
        return ", ".join(bits) or "nothing to send"


def status_note() -> str:
    if settings.MAIL_DRY_RUN:
        return "Dry run is ON — messages are recorded but never delivered."
    if not settings.smtp_configured():
        return "SMTP is not configured. Set JOBSCOUT_SMTP_HOST and JOBSCOUT_MAIL_FROM."
    return f"Live · {settings.SMTP_USER or settings.MAIL_FROM} via {settings.SMTP_HOST}:{settings.SMTP_PORT}"


def _build(to_addr: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    from_name = settings.MAIL_FROM_NAME or settings.APP_NAME
    msg["From"] = f"{from_name} <{settings.MAIL_FROM}>"
    msg["To"] = to_addr
    # Collapse newlines: EmailMessage would fold them, but a single-line
    # subject is what every client expects anyway.
    msg["Subject"] = " ".join((subject or "").split())
    if settings.MAIL_REPLY_TO:
        msg["Reply-To"] = settings.MAIL_REPLY_TO
    msg["X-Mailer"] = settings.APP_NAME
    msg.set_content(body or "")
    return msg


class _Transport:
    """Lazily opened SMTP connection, reused across a batch."""

    def __init__(self) -> None:
        self._smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    def __enter__(self) -> "_Transport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _connect(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        if self._smtp is not None:
            return self._smtp
        context = ssl.create_default_context()
        if settings.SMTP_SSL:
            smtp: smtplib.SMTP | smtplib.SMTP_SSL = smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, timeout=30, context=context
            )
        else:
            smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
            smtp.ehlo()
            if settings.SMTP_STARTTLS:
                smtp.starttls(context=context)
                smtp.ehlo()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        self._smtp = smtp
        return smtp

    def send(self, msg: EmailMessage) -> None:
        self._connect().send_message(msg)

    def close(self) -> None:
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except smtplib.SMTPException:
                pass
            self._smtp = None


def send_batch(
    user_id: int,
    jobs: Sequence[Mapping[str, Any]],
    *,
    dry_run: bool | None = None,
) -> SendReport:
    """Send (or simulate) a batch.

    Each job is ``{"to": str, "subject": str, "body": str,
    "employer_id": str | None}``. Every attempt lands in the ``emails`` table,
    whichever way it goes.
    """
    report = SendReport()
    if not jobs:
        return report

    dry = settings.MAIL_DRY_RUN if dry_run is None else bool(dry_run)
    if not dry and not settings.smtp_configured():
        report.messages.append("SMTP is not configured — nothing was sent.")
        report.skipped = len(jobs)
        return report

    already = repo.emails_sent_today(user_id)
    budget = max(0, settings.MAIL_DAILY_CAP - already)
    if budget <= 0:
        report.messages.append(
            f"Daily cap reached ({settings.MAIL_DAILY_CAP} messages). Nothing was sent."
        )
        report.skipped = len(jobs)
        return report

    with _Transport() as transport:
        for job in jobs:
            to_addr = str(job.get("to") or "").strip()
            subject = str(job.get("subject") or "")
            body = str(job.get("body") or "")
            emp_id = job.get("employer_id") or None

            if not valid_email(to_addr):
                report.skipped += 1
                report.messages.append(f"Skipped — not a valid address: {to_addr or '(blank)'}")
                repo.log_email(user_id, emp_id, to_addr, subject, body, "invalid", "bad address")
                continue
            if not subject.strip() or not body.strip():
                report.skipped += 1
                report.messages.append(f"Skipped {to_addr} — subject or body is empty.")
                continue
            if report.delivered >= budget:
                report.skipped += 1
                report.messages.append(f"Skipped {to_addr} — daily cap reached.")
                continue

            if dry:
                repo.log_email(user_id, emp_id, to_addr, subject, body, "simulated")
                report.simulated += 1
                continue

            try:
                transport.send(_build(to_addr, subject, body))
            except Exception as exc:
                log.warning("send to %s failed: %s", to_addr, exc)
                repo.log_email(user_id, emp_id, to_addr, subject, body, "failed", str(exc))
                report.failed += 1
                report.messages.append(f"Failed for {to_addr}: {exc}")
                # A dead connection would fail every remaining job identically.
                if isinstance(exc, (smtplib.SMTPServerDisconnected, OSError)):
                    transport.close()
            else:
                repo.log_email(user_id, emp_id, to_addr, subject, body, "sent")
                report.sent += 1

    return report


def send_test(user_id: int, to_addr: str) -> SendReport:
    return send_batch(
        user_id,
        [
            {
                "to": to_addr,
                "subject": f"{settings.APP_NAME} test message",
                "body": (
                    f"This is a test message from {settings.APP_NAME}.\n\n"
                    "If you are reading it, SMTP delivery works.\n"
                ),
                "employer_id": None,
            }
        ],
    )
