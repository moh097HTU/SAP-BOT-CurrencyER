# services/notify.py
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from services.config import config

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]

def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]

def _get_token() -> str:
    """
    Acquire an app-only token using MSAL (client credentials).
    Import msal lazily so the project runs even if emailing is disabled.
    """
    cfg = config()
    try:
        import msal
    except Exception as e:
        raise RuntimeError("Emailing is enabled but 'msal' is not installed.") from e

    app = msal.ConfidentialClientApplication(
        client_id=cfg["OUTLOOK_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{cfg['OUTLOOK_TENANT_ID']}",
        client_credential=cfg["OUTLOOK_CLIENT_SECRET"],
    )
    result = app.acquire_token_silent(_SCOPES, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=_SCOPES)
    if not result or "access_token" not in result:
        raise RuntimeError(f"Could not acquire Graph token: {result}")
    return result["access_token"]

def _file_attachment_dict(path: Path, max_mb: int) -> Optional[Dict[str, Any]]:
    """
    Build Graph fileAttachment payload for files up to max_mb (simple attach limit).
    Returns None if too large or missing.
    """
    try:
        if not path.exists() or not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_mb * 1024 * 1024:
            return None
        content = path.read_bytes()
        return {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": path.name,
            "contentBytes": base64.b64encode(content).decode("ascii"),
        }
    except Exception:
        return None

def _build_html_body(batch_id: str,
                     received_count: int,
                     created_count: int,
                     failed_rows: List[Dict[str, Any]],
                     duration_sec: Optional[float]) -> str:
    rows = []
    for r in failed_rows:
        p = r.get("payload", {})
        err = r.get("error") or r.get("dialog_text") or ""
        rows.append(f"""
          <tr>
            <td>{r.get('index','')}</td>
            <td>{p.get('ExchangeRateType','')}</td>
            <td>{p.get('FromCurrency','')}</td>
            <td>{p.get('ToCurrency','')}</td>
            <td>{p.get('ValidFrom','')}</td>
            <td>{p.get('Quotation','')}</td>
            <td>{p.get('ExchangeRate','')}</td>
            <td>{r.get('status','')}</td>
            <td>{(err or '').replace('<','&lt;').replace('>','&gt;')}</td>
          </tr>
        """)
    rows_html = "\n".join(rows) or "<tr><td colspan='10'>—</td></tr>"
    dur = f"{duration_sec:.1f}s" if duration_sec is not None else "n/a"
    created_pct = f"{(created_count/received_count*100):.1f}%" if received_count else "n/a"
    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif">
      <h2>[SAP-BOT] Batch {batch_id} completed</h2>
      <p><b>Received:</b> {received_count} &nbsp;|&nbsp; <b>Created:</b> {created_count} ({created_pct}) &nbsp;|&nbsp; <b>Failed:</b> {len(failed_rows)} &nbsp;|&nbsp; <b>Duration:</b> {dur}</p>
      <h3>Failures</h3>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">
        <thead>
          <tr>
            <th>#</th><th>Type</th><th>From</th><th>To</th><th>Date</th>
            <th>Quotation</th><th>Rate</th><th>Status</th><th>Error</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p style="margin-top:12px">Full JSON/CSV attached. attached when size allowed; if any were too large, their paths are listed in the table.</p>
    </div>
    """

def send_batch_email(
    batch_id: str,
    received_count: int,
    result_obj: Dict[str, Any],
    failed_rows: List[Dict[str, Any]],
    attachment_paths: List[str],
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Sends a summary email via Microsoft Graph to OUTLOOK_TO/CC.
    attachment_paths: list of files to attach (failed json/csv).
    Returns a dict with 'ok' and 'attached' lists.
    """
    cfg = config()
    if not cfg.get("EMAIL_ENABLED"):
        return {"ok": False, "reason": "email_disabled"}

    # Prepare recipients
    to_list = _split_csv(cfg.get("OUTLOOK_TO", ""))
    if not to_list:
        return {"ok": False, "reason": "no_to_recipients"}
    cc_list = _split_csv(cfg.get("OUTLOOK_CC", ""))

    # Subject/body
    created_count = int(result_obj.get("created", 0))
    subject = f"[SAP-BOT] Batch {batch_id}: {created_count}/{received_count} created – {len(failed_rows)} failed"
    html_body = _build_html_body(batch_id, received_count, created_count, failed_rows, duration_sec)

    # Build attachments (respect simple attach size)
    max_mb = int(cfg.get("EMAIL_MAX_ATTACH_MB") or 3)
    attached = []
    attachments = []
    for p in attachment_paths:
        att = _file_attachment_dict(Path(p), max_mb=max_mb)
        if att:
            attachments.append(att)
            attached.append(os.path.basename(p))
    # Graph API payload
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to_list],
    }
    if cc_list:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_list]
    if attachments:
        message["attachments"] = attachments

    # Send
    token = _get_token()
    import requests  
    sender_upn = cfg["OUTLOOK_SENDER"] or to_list[0]  # fallback
    url = f"{GRAPH_BASE}/users/{sender_upn}/sendMail"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"message": message, "saveToSentItems": True}),
        timeout=30,
    )
    if resp.status_code not in (202, 200):
        return {"ok": False, "reason": f"graph_send_failed {resp.status_code}: {resp.text}"}

    return {"ok": True, "attached": attached, "to": to_list, "cc": cc_list}
