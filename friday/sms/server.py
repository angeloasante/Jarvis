"""SMS Webhook Server — receives inbound Twilio SMS, processes through FRIDAY, replies.

Run: python -m friday.sms.server
Expose: ngrok http 3200

Then set Twilio webhook URL to: https://your-ngrok.ngrok.io/sms
"""

import asyncio
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs
from threading import Thread

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent.parent / ".env")

log = logging.getLogger("friday.sms.server")

PORT = int(os.getenv("SMS_PORT", "3200"))

# Allowed phone numbers (only process SMS from these)
ALLOWED_NUMBERS = os.getenv("SMS_ALLOWED_NUMBERS", os.getenv("CONTACT_PHONE", "")).split(",")
ALLOWED_NUMBERS = [n.strip() for n in ALLOWED_NUMBERS if n.strip()]


class SMSHandler(BaseHTTPRequestHandler):
    """Handle inbound Twilio SMS webhooks."""

    friday = None  # Set by start_server()
    loop = None

    def do_POST(self):
        if self.path != "/sms":
            self.send_response(404)
            self.end_headers()
            return

        # Parse form data
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        params = parse_qs(body)

        from_number = params.get("From", [""])[0]
        twilio_number = params.get("To", [""])[0]  # The Twilio number they texted
        message_body = params.get("Body", [""])[0].strip()

        log.info(f"SMS from {from_number}: {message_body[:50]}")

        # Security: only process from allowed numbers
        if ALLOWED_NUMBERS and from_number not in ALLOWED_NUMBERS:
            log.warning(f"SMS from unauthorized number: {from_number}")
            self._reply("Unauthorized.")
            return

        if not message_body:
            self._reply("Empty message.")
            return

        if not self.friday or not self.loop:
            self._reply("FRIDAY not connected.")
            return

        # Always ack Twilio immediately with empty TwiML, then process + reply
        # via outbound SMS API. TwiML inline replies are unreliable on UK numbers.
        self._reply_empty()
        Thread(
            target=self._process_and_reply,
            args=(message_body, from_number, twilio_number),
            daemon=True,
            name="friday-sms-process",
        ).start()

    def _process_and_reply(self, message_body: str, from_number: str, twilio_number: str = ""):
        """Process through full FRIDAY pipeline, send result as outbound SMS.

        1. Try fast_path (TV, greetings) — instant, no LLM
        2. Fall through to dispatch_background (full 7-tier pipeline)
        All replies sent via Twilio outbound API (not TwiML).
        """
        import re
        from threading import Event

        try:
            log.info(f"Processing SMS: '{message_body[:50]}' from {from_number}")
            print(f"  [SMS] Processing: '{message_body[:50]}' from {from_number}", flush=True)

            # Try fast_path first — needs the main event loop
            import asyncio
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.friday.fast_path(message_body), self.loop,
                )
                fast_result = future.result(timeout=5)
                if fast_result is not None:
                    log.info(f"SMS fast_path hit: {fast_result[:50]}")
                    print(f"  [SMS] fast_path: {fast_result[:50]}", flush=True)
                    self._send_sms(from_number, fast_result, from_twilio=twilio_number)
                    return
            except Exception as e:
                log.info(f"SMS fast_path miss: {e}")

            # Full pipeline via dispatch_background
            collected = []
            done = Event()

            def on_update(msg):
                if msg.startswith("CHUNK:"):
                    collected.append(msg[6:])
                elif msg.startswith("DONE:") or msg.startswith("ERROR:"):
                    done.set()

            log.info("SMS dispatching to background...")
            print("  [SMS] dispatching to background...", flush=True)
            self.friday.dispatch_background(message_body, on_update=on_update)

            # Wait up to 55s
            done.wait(timeout=55)
            log.info(f"SMS dispatch done, collected {len(collected)} chunks")

            response = "".join(collected).strip()
            if not response:
                response = "Done."

            # Strip markdown for SMS
            response = re.sub(r'\*\*(.+?)\*\*', r'\1', response)
            response = re.sub(r'\*(.+?)\*', r'\1', response)
            response = re.sub(r'`(.+?)`', r'\1', response)
            response = re.sub(r'^#+\s+', '', response, flags=re.MULTILINE)

            if len(response) > 1500:
                response = response[:1497] + "..."

            self._send_sms(from_number, response, from_twilio=twilio_number)

        except Exception as e:
            log.error(f"SMS process error: {e}")
            self._send_sms(from_number, f"Something went wrong: {e}", from_twilio=twilio_number)

    def _send_sms(self, to: str, message: str, from_twilio: str = ""):
        """Send outbound SMS via Twilio.

        Uses the same Twilio number they texted (from_twilio) so
        UK→UK and US→US always match. Falls back to TWILIO_PHONE_NUMBER env var.
        """
        try:
            from twilio.rest import Client
            client = Client(
                os.getenv("TWILIO_ACCOUNT_SID", ""),
                os.getenv("TWILIO_AUTH_TOKEN", ""),
            )
            from_number = from_twilio or os.getenv("TWILIO_PHONE_NUMBER", "")
            client.messages.create(
                body=message,
                from_=from_number,
                to=to,
            )
            log.info(f"SMS reply sent to {to} from {from_number}: {message[:50]}")
        except Exception as e:
            log.error(f"Failed to send SMS reply: {e}")

    def _reply(self, message: str):
        """Send TwiML response with a message."""
        from xml.sax.saxutils import escape
        safe_msg = escape(message)
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{safe_msg}</Message>
</Response>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.end_headers()
        self.wfile.write(twiml.encode("utf-8"))

    def _reply_empty(self):
        """Acknowledge Twilio webhook with empty response (no SMS back).

        We'll send the actual reply as a separate outbound SMS once
        FRIDAY finishes processing. This prevents Twilio's 15s timeout
        from killing the connection and dropping messages.
        """
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(twiml.encode("utf-8"))

    def log_message(self, format, *args):
        """Log HTTP requests."""
        log.info(format % args)

    def do_GET(self):
        """Health check."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"friday-sms"}')
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"FRIDAY SMS Server")


def start_server(friday=None, loop=None):
    """Start the SMS webhook server in a background thread."""
    SMSHandler.friday = friday
    SMSHandler.loop = loop

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("0.0.0.0", PORT), SMSHandler)
    thread = Thread(target=server.serve_forever, daemon=True, name="friday-sms")
    thread.start()
    log.info(f"SMS webhook server running on port {PORT}")
    print(f"  [bold green]:: SMS server ACTIVE on port {PORT}[/bold green]")
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Standalone mode — start FRIDAY + SMS server
    from friday.core.orchestrator import FridayCore

    friday = FridayCore()
    loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    Thread(target=run_loop, daemon=True).start()

    print(f"FRIDAY SMS Server — port {PORT}")
    print(f"Allowed numbers: {ALLOWED_NUMBERS}")
    print(f"Set Twilio webhook to: http://your-server:{PORT}/sms")
    print()

    start_server(friday=friday, loop=loop)

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
