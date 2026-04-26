"""
GetterDone Python SDK — webhook utilities.

Standalone helpers that have no dependency on the GetterDone client instance.
"""

import hashlib
import hmac


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Verify a GetterDone webhook ``X-GetterDone-Signature`` header.

    The server signs the raw request body with HMAC-SHA256 and sends the digest
    as ``sha256=<hex>``.  This function re-computes the digest using your webhook
    secret and does a constant-time comparison so timing attacks are impossible.

    Parameters
    ----------
    raw_body : bytes
        The raw (undecoded) request body exactly as received — do not parse or
        normalise it before passing it here.
    signature_header : str
        The full value of the ``X-GetterDone-Signature`` header, e.g.
        ``"sha256=abc123..."``.
    secret : str
        Your webhook signing secret (set when configuring the webhook endpoint).

    Returns
    -------
    bool
        ``True`` if the signature is valid, ``False`` for **any** reason
        (wrong secret, malformed header, missing prefix, empty inputs, etc.).

    Examples
    --------
    ::

        from getterdone import verify_webhook_signature

        @app.post("/webhook")
        def handle_webhook(request):
            if not verify_webhook_signature(
                request.body,
                request.headers["X-GetterDone-Signature"],
                os.environ["WEBHOOK_SECRET"],
            ):
                abort(401)
            process_event(request.json())
    """
    try:
        if not isinstance(raw_body, bytes):
            return False
        if not isinstance(signature_header, str):
            return False
        if not isinstance(secret, str):
            return False

        prefix = "sha256="
        if not signature_header.startswith(prefix):
            return False

        provided_hex = signature_header[len(prefix):]
        if not provided_hex:
            return False

        expected_hex = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_hex, provided_hex)
    except Exception:
        return False
