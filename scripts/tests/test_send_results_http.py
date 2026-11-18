"""Exercise the real sender, jq and curl against a temporary loopback TLS receiver."""
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tarfile
import threading
import unittest
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from tempfile import TemporaryDirectory


SENDER = Path(__file__).resolve().parents[1] / "result_server/send_results.sh"
RESULT_ID = "11111111-2222-4333-8444-555555555555"


class SenderReceiptTest(unittest.TestCase):
    def run_sender(self, lose_receipt):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert, key = root / "cert.pem", root / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", str(key), "-out", str(cert), "-days", "1",
                            "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1"],
                           check=True, capture_output=True)
            (root / ".curlrc").write_text("retry = 1\nretry-all-errors\n")
            results = root / "results"
            results.mkdir()
            archive = results / "profile.tgz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("measurement.csv")
                data = b"value\n12\n"
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
            ref = {"type": "file_reference", "path": "results/profile.tgz"}
            refs = [False, "invalid", {"type": "file_reference", "path": [ref["path"]]}, ref, ref]
            if lose_receipt:
                (results / "after.tgz").write_bytes(archive.read_bytes())
                refs.append({"type": "file_reference", "path": "results/after.tgz"})
            source = {"code": "sample", "fom_breakdown": {"sections": [False, {"artifacts": refs}]}}
            (results / "result1.json").write_text(json.dumps(source))
            calls = []
            received = []

            class Receiver(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    calls.append(self.path)
                    body = self.rfile.read(int(self.headers["Content-Length"]))
                    if self.path == "/api/ingest/result":
                        reply = {"id": RESULT_ID, "timestamp": "20260101_120000"}
                    elif self.path == "/api/ingest/measurement-artifact":
                        header = ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode()
                        message = BytesParser(policy=policy.default).parsebytes(header + body)
                        fields = {part.get_param("name", header="content-disposition"):
                                  part.get_payload(decode=True) for part in message.iter_parts()}
                        received.append((fields["id"], fields["artifact_path"], fields["file"]))
                        if lose_receipt:
                            self.close_connection = True
                            return
                        reply = {"status": "uploaded"}
                    else:
                        self.send_error(404)
                        return
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps(reply, separators=(",", ":")).encode())

            with HTTPServer(("127.0.0.1", 0), Receiver) as server:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cert, key)
                server.socket = context.wrap_socket(server.socket, server_side=True)
                worker = threading.Thread(target=server.serve_forever)
                worker.start()
                try:
                    env = dict(os.environ, CURL_HOME=tmp, CURL_CA_BUNDLE=str(cert),
                               RESULT_SERVER_CLIENT_CERT=str(cert), RESULT_SERVER_CLIENT_KEY=str(key),
                               RESULT_SERVER=f"https://127.0.0.1:{server.server_port}",
                               NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
                    result = subprocess.run(["bash", str(SENDER)], cwd=root, env=env,
                                            capture_output=True, text=True, timeout=20)
                finally:
                    server.shutdown()
                    worker.join()
            self.assertEqual(calls, ["/api/ingest/result", "/api/ingest/measurement-artifact"])
            self.assertEqual(received, [(RESULT_ID.encode(), ref["path"].encode(), archive.read_bytes())])
            self.assertEqual(json.loads((results / "result1.json").read_text())["_server_uuid"], RESULT_ID)
            if lose_receipt:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Check PA storage status using Result ID " + RESULT_ID, result.stderr)
                self.assertNotIn("All done.", result.stdout)
            else:
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_later_valid_reference_arrives_once(self):
        self.run_sender(False)

    def test_lost_pa_receipt_stops_without_repost(self):
        self.run_sender(True)


if __name__ == "__main__":
    unittest.main()
