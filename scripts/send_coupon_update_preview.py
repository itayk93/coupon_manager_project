#!/usr/bin/env python
"""Send a sample coupon update summary email for design preview."""

import argparse
from datetime import datetime, timezone
from types import SimpleNamespace

from app import create_app


def build_sample_items() -> list[dict]:
    """Return a fixed list of sample coupon rows for the preview email."""
    return [
        {
            "coupon_code": "1277024444-6052",
            "company": "ביג קניון",
            "old_usage": 170.0,
            "new_usage": 340.0,
            "delta": 170.0,
            "remaining_value": 330.0,
        },
        {
            "coupon_code": "115000386-9340",
            "company": "Xtra Gift",
            "old_usage": 194.0,
            "new_usage": 212.0,
            "delta": 18.0,
            "remaining_value": 288.0,
        },
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipient",
        default="itayk93@gmail.com",
        help="Email address that should receive the preview",
    )
    parser.add_argument(
        "--first-name",
        default="Itay",
        help="Recipient first name placeholder used inside the template",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only render the HTML and print it to stdout without sending an email",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app()

    with app.app_context():
        from flask import render_template
        from app.helpers import send_email, SENDER_EMAIL, SENDER_NAME

        user = SimpleNamespace(first_name=args.first_name, email=args.recipient)
        sample_items = build_sample_items()

        html = render_template(
            "emails/coupon_updates_summary.html",
            user=user,
            items=sample_items,
            success_count=len(sample_items),
            failure_count=0,
            started=datetime.now(timezone.utc).isoformat(),
            ended=datetime.now(timezone.utc).isoformat(),
        )

        if args.dry_run:
            print(html)
            return

        send_email(
            sender_email=SENDER_EMAIL,
            sender_name=SENDER_NAME,
            recipient_email=args.recipient,
            recipient_name=args.first_name,
            subject="סיכום עדכון קופונים – גרסת תצוגה",
            html_content=html,
        )
        print(f"Preview email sent to {args.recipient}")


if __name__ == "__main__":
    main()
