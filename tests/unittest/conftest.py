import asyncio
import json
import os
import threading
import time
import typing
from asyncio import sleep
from collections import defaultdict
from urllib.parse import parse_qs

import pytest
import trustme
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
    load_pem_private_key,
)
from httpx import URL
from uvicorn.config import Config
from uvicorn.main import Server

ENVIRONMENT_VARIABLES = {
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSLKEYLOGFILE",
}


@pytest.fixture(
    params=[
        pytest.param("asyncio", marks=pytest.mark.asyncio),
        pytest.param("trio", marks=pytest.mark.trio),
    ]
)
def async_environment(request: typing.Any) -> str:
    """
    Mark a test function to be run on both asyncio and trio.
    Equivalent to having a pair of tests, each respectively marked with
    '@pytest.mark.asyncio' and '@pytest.mark.trio'.
    Intended usage:
    ```
    @pytest.mark.usefixtures("async_environment")
    async def my_async_test():
        ...
    ```
    """
    return request.param


@pytest.fixture(scope="function", autouse=True)
def clean_environ():
    """Keeps os.environ clean for every test without having to mock os.environ"""
    original_environ = os.environ.copy()
    os.environ.clear()
    os.environ.update(
        {
            k: v
            for k, v in original_environ.items()
            if k not in ENVIRONMENT_VARIABLES and k.lower() not in ENVIRONMENT_VARIABLES
        }
    )
    yield
    os.environ.clear()
    os.environ.update(original_environ)


async def app(scope, receive, send):
    assert scope["type"] == "http"
    print("scope_path:", scope["path"])
    if scope["path"].startswith("/slow_response"):
        await slow_response(scope, receive, send)
    elif scope["path"].startswith("/status"):
        await status_code(scope, receive, send)
    elif scope["path"].startswith("/echo_path"):
        await echo_path(scope, receive, send)
    elif scope["path"].startswith("/echo_params"):
        await echo_params(scope, receive, send)
    elif scope["path"].startswith("/echo_body"):
        await echo_body(scope, receive, send)
    elif scope["path"].startswith("/echo_binary"):
        await echo_binary(scope, receive, send)
    elif scope["path"].startswith("/echo_headers"):
        await echo_headers(scope, receive, send)
    elif scope["path"].startswith("/echo_cookies"):
        await echo_cookies(scope, receive, send)
    elif scope["path"].startswith("/set_headers"):
        await set_headers(scope, receive, send)
    elif scope["path"].startswith("/set_cookies"):
        await set_cookies(scope, receive, send)
    elif scope["path"].startswith("/redirect_301"):
        await redirect_301(scope, receive, send)
    elif scope["path"].startswith("/json"):
        await hello_world_json(scope, receive, send)
    elif scope["path"].startswith("http://"):
        await http_proxy(scope, receive, send)
    elif scope["method"] == "CONNECT":
        await https_proxy(scope, receive, send)
    else:
        await hello_world(scope, receive, send)


async def hello_world(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain; charset=utf-8"]],
        }
    )
    await send({"type": "http.response.body", "body": b"Hello, world!"})


async def hello_world_json(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": b'{"Hello": "world!"}'})


async def http_proxy(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": b'{"Hello": "http_proxy!"}'})


async def https_proxy(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": b'{"Hello": "https_proxy!"}'})


async def slow_response(scope, receive, send):
    await sleep(0.2)
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": b"Hello, world!"})


async def status_code(scope, receive, send):
    status_code = int(scope["path"].replace("/status/", ""))
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": b"Hello, world!"})


async def echo_body(scope, receive, send):
    body = b""
    more_body = True

    while more_body:
        message = await receive()
        body += message.get("body", b"")
        more_body = message.get("more_body", False)

    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    print("server: received:", body)
    await send({"type": "http.response.body", "body": body})


async def echo_path(scope, receive, send):
    body = {"path": scope["path"]}
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})

async def echo_params(scope, receive, send):
    body = {"params": parse_qs(scope["query_string"].decode())}
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})

async def echo_binary(scope, receive, send):
    body = b""
    more_body = True

    while more_body:
        message = await receive()
        body += message.get("body", b"")
        more_body = message.get("more_body", False)

    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/octet-stream"]],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def echo_headers(scope, receive, send):
    body = defaultdict(list)
    for name, value in scope.get("headers", []):
        body[name.capitalize().decode()].append(value.decode() )

    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})


async def echo_cookies(scope, receive, send):
    headers = scope.get("headers", [])
    cookies = {}
    for header in headers:
        if header[0].decode() == "cookie":
            cookies_header = header[1].decode()
            for cookie in cookies_header.split(";"):
                name, value = cookie.strip().split("=")
                cookies[name] = value
            break
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(cookies).encode()})


async def set_headers(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"],
                [b"x-test", b"test"],
                [b"x-test", b"test2"],
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"Hello, world!"})


async def set_cookies(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"],
                [b"set-cookie", b"foo=bar"],
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"Hello, world!"})

async def redirect_301(scope, receive, send):
    await send(
        {"type": "http.response.start", "status": 301, "headers": [[b"location", b"/"]]}
    )
    await send({"type": "http.response.body", "body": b"Redirecting..."})


@pytest.fixture(scope="session")
def cert_authority():
    return trustme.CA()


@pytest.fixture(scope="session")
def ca_cert_pem_file(cert_authority):
    with cert_authority.cert_pem.tempfile() as tmp:
        yield tmp


@pytest.fixture(scope="session")
def localhost_cert(cert_authority):
    return cert_authority.issue_cert("localhost")


@pytest.fixture(scope="session")
def cert_pem_file(localhost_cert):
    with localhost_cert.cert_chain_pems[0].tempfile() as tmp:
        yield tmp


@pytest.fixture(scope="session")
def cert_private_key_file(localhost_cert):
    with localhost_cert.private_key_pem.tempfile() as tmp:
        yield tmp


@pytest.fixture(scope="session")
def cert_encrypted_private_key_file(localhost_cert):
    # Deserialize the private key and then reserialize with a password
    private_key = load_pem_private_key(
        localhost_cert.private_key_pem.bytes(), password=None, backend=default_backend()
    )
    encrypted_private_key_pem = trustme.Blob(
        private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.TraditionalOpenSSL,
            BestAvailableEncryption(password=b"password"),
        )
    )
    with encrypted_private_key_pem.tempfile() as tmp:
        yield tmp


class TestServer(Server):
    @property
    def url(self) -> URL:
        protocol = "https" if self.config.is_ssl else "http"
        return URL(f"{protocol}://{self.config.host}:{self.config.port}/")

    def install_signal_handlers(self) -> None:
        # Disable the default installation of handlers for signals such as SIGTERM,
        # because it can only be done in the main thread.
        pass

    async def serve(self, sockets=None):
        self.restart_requested = asyncio.Event()

        loop = asyncio.get_event_loop()
        tasks = {
            loop.create_task(super().serve(sockets=sockets)),
            loop.create_task(self.watch_restarts()),
        }
        await asyncio.wait(tasks)

    async def restart(self) -> None:  # pragma: nocover
        # This coroutine may be called from a different thread than the one the
        # server is running on, and from an async environment that's not asyncio.
        # For this reason, we use an event to coordinate with the server
        # instead of calling shutdown()/startup() directly, and should not make
        # any asyncio-specific operations.
        self.started = False
        self.restart_requested.set()
        while not self.started:
            await sleep(0.2)

    async def watch_restarts(self):  # pragma: nocover
        while True:
            if self.should_exit:
                return

            try:
                await asyncio.wait_for(self.restart_requested.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            self.restart_requested.clear()
            await self.shutdown()
            await self.startup()


def serve_in_thread(server: Server):
    thread = threading.Thread(target=server.run)
    thread.start()
    try:
        while not server.started:
            time.sleep(1e-3)
        yield server
    finally:
        server.should_exit = True
        thread.join()


@pytest.fixture(scope="session")
def server():
    config = Config(app=app, lifespan="off", loop="asyncio")
    server = TestServer(config=config)
    yield from serve_in_thread(server)


@pytest.fixture(scope="session")
def https_server(cert_pem_file, cert_private_key_file):
    config = Config(
        app=app,
        lifespan="off",
        ssl_certfile=cert_pem_file,
        ssl_keyfile=cert_private_key_file,
        port=8001,
        loop="asyncio",
    )
    server = TestServer(config=config)
    yield from serve_in_thread(server)
