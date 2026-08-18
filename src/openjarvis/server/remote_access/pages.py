"""Small, self-contained login pages for the remote test gateway."""

from __future__ import annotations

from html import escape
from json import dumps
from urllib.parse import quote, urlsplit

from fastapi.responses import HTMLResponse

_BASE_STYLE = """
*{box-sizing:border-box}body{min-height:100vh;margin:0;display:grid;place-items:center;
padding:24px;background:#02070d;color:#dffaff;font:16px system-ui,sans-serif}
main{width:min(100%,420px);padding:32px;border:1px solid #17647a;
border-radius:18px;background:#06121dcc;box-shadow:0 24px 80px #000b}
h1{margin:0 0 8px;letter-spacing:.24em}p{color:#91b5be;line-height:1.5}
a,button{display:block;width:100%;margin-top:22px;padding:13px;
border:1px solid #38e7ff;border-radius:999px;background:#0b3e4c;
color:#eaffff;font-weight:700;text-align:center;text-decoration:none}
label{display:block;margin:18px 0 7px;color:#53eaff;font-size:12px;
letter-spacing:.12em;text-transform:uppercase}
input{width:100%;padding:13px;border:1px solid #195a6b;border-radius:9px;
background:#020a11;color:#fff;font-size:16px}.error{padding:10px;
border-left:3px solid #ff6878;background:#2a0b12;color:#ffc4ca}
small{display:block;margin-top:18px;color:#67858c;text-align:center}
""".strip()


def safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/jarvis"
    lowered = value.lower()
    if "\\" in value or "%2f" in lowered or "%5c" in lowered:
        return "/jarvis"
    if any(ord(character) < 32 for character in value):
        return "/jarvis"
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc and parsed.path.startswith("/"):
        return value
    return "/jarvis"


def login_page(next_path: str, *, invalid: bool = False) -> HTMLResponse:
    error = (
        '<p class="error" role="alert">Usuário ou senha incorretos.</p>'
        if invalid
        else ""
    )
    document = f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenJarvis — acesso remoto</title>
<style>{_BASE_STYLE}</style></head><body><main><h1>JARVIS</h1>
<p>Acesso protegido ao ambiente remoto de teste do OpenJarvis.</p>{error}
<form method="post" action="/__openjarvis/login" accept-charset="UTF-8">
<input type="hidden" name="next" value="{escape(next_path, quote=True)}">
<label for="username">Usuário</label>
<input id="username" name="username" autocomplete="username"
autocapitalize="none" autocorrect="off" spellcheck="false" required autofocus>
<label for="password">Senha</label>
<input id="password" name="password" type="password"
autocomplete="current-password" required>
<button type="submit">ENTRAR NO OPENJARVIS</button>
</form><small>Sessão temporária protegida.</small></main></body></html>"""
    return _html_response(document, allow_form=True)


def login_success(next_path: str, continuation_token: str) -> HTMLResponse:
    next_path = safe_next(next_path)
    destination = (
        "/__openjarvis/continue?token="
        f"{quote(continuation_token, safe='')}&next={quote(next_path, safe='')}"
    )
    escaped_destination = escape(destination, quote=True)
    document = f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="1;url={escaped_destination}">
<title>OpenJarvis — acesso autorizado</title>
<style>{_BASE_STYLE}</style></head><body><main>
<h1>ACESSO AUTORIZADO</h1><p>Preparando a sessão segura…</p>
<a href="{escaped_destination}">CONTINUAR</a></main></body></html>"""
    return _html_response(document)


def continuation_success(next_path: str) -> HTMLResponse:
    next_path = safe_next(next_path)
    destination = escape(next_path, quote=True)
    script_destination = dumps(next_path)
    document = f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="1;url={destination}">
<title>OpenJarvis — sessão ativa</title>
<style>{_BASE_STYLE}</style></head><body><main><h1>SESSÃO ATIVA</h1>
<p>Abrindo o OpenJarvis…</p>
<a href="{destination}">ABRIR AGORA</a></main>
<script>window.location.replace({script_destination});</script></body></html>"""
    return _html_response(document, allow_script=True)


def _html_response(
    document: str, *, allow_form: bool = False, allow_script: bool = False
) -> HTMLResponse:
    policy = [
        "default-src 'none'",
        "style-src 'unsafe-inline'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ]
    if allow_form:
        policy.append("form-action 'self'")
    if allow_script:
        policy[0] = "default-src 'self'"
        policy.append("script-src 'unsafe-inline'")
    return HTMLResponse(
        document,
        status_code=200,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "; ".join(policy),
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        },
    )


__all__ = ["continuation_success", "login_page", "login_success", "safe_next"]
