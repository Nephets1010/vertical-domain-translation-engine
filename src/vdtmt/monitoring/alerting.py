"""告警（企业级：规则化、可路由、密钥不硬编码）。

告警经日志 + 指标输出；如需外发（邮件/Webhook），通过环境变量注入
目标地址与令牌，绝不明文写在代码里。
"""

from __future__ import annotations

import os
import smtplib
import json
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from ..config import get_settings
from ..logging_setup import get_logger

logger = get_logger("vdtmt.monitoring.alerting")


@dataclass
class Alert:
    rule: str
    severity: str  # info | warning | critical
    message: str
    context: dict = None  # type: ignore


class Notifier(Protocol):
    def send(self, alert: Alert) -> None: ...


class LogNotifier:
    """默认通知器：写入结构化日志。"""

    def send(self, alert: Alert) -> None:
        logger.warning(
            "ALERT raised",
            extra={"context": {
                "rule": alert.rule, "severity": alert.severity,
                "message": alert.message, "ctx": alert.context or {},
            }},
        )


class WebhookNotifier:
    """Webhook 通知器：目标地址与令牌来自环境变量。"""

    def __init__(self) -> None:
        self.url = os.getenv("ALERT_WEBHOOK_URL", "")
        self.token = os.getenv("ALERT_WEBHOOK_TOKEN", "")

    def send(self, alert: Alert) -> None:
        if not self.url:
            return
        try:
            import urllib.request

            payload = json.dumps({
                "rule": alert.rule, "severity": alert.severity,
                "message": alert.message, "context": alert.context or {},
            }).encode("utf-8")
            req = urllib.request.Request(
                self.url, data=payload, headers={"Content-Type": "application/json"}
            )
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:  # 告警失败不应影响主流程
            logger.error("webhook alert failed: %s", exc)


class EmailNotifier:
    """邮件通知器：SMTP 凭据来自环境变量。"""

    def send(self, alert: Alert) -> None:
        host = os.getenv("ALERT_SMTP_HOST")
        if not host:
            return
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[VDT-MT] {alert.severity}: {alert.rule}"
            msg.set_content(alert.message)
            msg["From"] = os.getenv("ALERT_SMTP_FROM", "vdtmt@localhost")
            msg["To"] = os.getenv("ALERT_SMTP_TO", "")
            with smtplib.SMTP(host, int(os.getenv("ALERT_SMTP_PORT", "25"))) as s:
                if os.getenv("ALERT_SMTP_USER"):
                    s.starttls()
                    s.login(os.getenv("ALERT_SMTP_USER"), os.getenv("ALERT_SMTP_PASS", ""))
                s.send_message(msg)
        except Exception as exc:
            logger.error("email alert failed: %s", exc)


class AlertManager:
    """告警中枢：聚合多条通知通道。"""

    def __init__(self) -> None:
        self.notifiers: list[Notifier] = [
            LogNotifier(), WebhookNotifier(), EmailNotifier()
        ]

    def raise_alert(
        self, rule: str, severity: str, message: str, context: dict | None = None
    ) -> None:
        alert = Alert(rule=rule, severity=severity, message=message, context=context)
        for n in self.notifiers:
            try:
                n.send(alert)
            except Exception:  # 单通道失败不影响其他
                pass


def get_alert_manager() -> AlertManager:
    return AlertManager()
