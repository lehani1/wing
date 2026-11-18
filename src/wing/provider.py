import asyncio
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from langchain_openai import ChatOpenAI


@dataclass(frozen=True)
class AzureConfig:
    deployment: str
    base_url: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls, model: str | None = None) -> "AzureConfig":
        deployment = (model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")).strip()
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        if not deployment or not endpoint or not key:
            raise ValueError(
                "Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and "
                "AZURE_OPENAI_DEPLOYMENT (or pass --model)."
            )

        url = urlsplit(endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/openai/v1"}
        ):
            raise ValueError("AZURE_OPENAI_ENDPOINT must be an HTTPS resource URL or its /openai/v1 URL.")
        base_url = endpoint if url.path else f"{endpoint}/openai/v1"
        return cls(deployment, f"{base_url}/", key)


def strip_diagnostics(request: httpx.Request) -> None:
    for name in list(request.headers):
        if name == "x-stainless-raw-response":
            # The SDK uses this flag to choose the response parser.
            continue
        if name.startswith("x-stainless-") or name in {
            "openai-organization", "openai-project", "traceparent", "tracestate",
            "baggage", "user-agent",
        }:
            del request.headers[name]


async def strip_async_diagnostics(request: httpx.Request) -> None:
    strip_diagnostics(request)


@contextmanager
def azure_model(config: AzureConfig, *, transport: httpx.BaseTransport | None = None):
    with httpx.Client(
        transport=transport,
        trust_env=False,
        event_hooks={"request": [strip_diagnostics]},
    ) as http_client:
        # Wing invokes the graph synchronously. Supply the async transport as
        # well so the adapter never builds an unfiltered default client.
        async_client = httpx.AsyncClient(
            trust_env=False,
            event_hooks={"request": [strip_async_diagnostics]},
        )
        try:
            yield ChatOpenAI(
                model=config.deployment,
                api_key=config.api_key,
                base_url=config.base_url,
                http_client=http_client,
                http_async_client=async_client,
                openai_proxy="",
                timeout=90,
                max_retries=2,
                use_responses_api=True,
                use_previous_response_id=False,
                store=False,
                include=["reasoning.encrypted_content"],
            )
        finally:
            # No async requests are issued by the synchronous graph.
            asyncio.run(async_client.aclose())
