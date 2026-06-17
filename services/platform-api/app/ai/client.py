from __future__ import annotations

import json
from urllib import parse, request

from azure.identity import DefaultAzureCredential

from app.core.config import settings


class AzureAIFoundryClient:
    def __init__(self) -> None:
        self.endpoint = settings.azure_ai_foundry_endpoint.strip()
        self.deployment_name = settings.azure_ai_foundry_deployment_name.strip()
        self.api_version = settings.azure_ai_foundry_api_version.strip()
        self.api_key = settings.azure_openai_api_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.deployment_name and self.api_version)

    def _url(self) -> str:
        if "/openai/deployments/" in self.endpoint:
            separator = "&" if "?" in self.endpoint else "?"
            return f"{self.endpoint}{separator}api-version={parse.quote(self.api_version)}"
        base = self.endpoint.rstrip("/")
        return f"{base}/openai/deployments/{parse.quote(self.deployment_name)}/chat/completions?api-version={parse.quote(self.api_version)}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
            return headers

        credential = DefaultAzureCredential(
            managed_identity_client_id=settings.azure_client_id or None,
            exclude_interactive_browser_credential=True,
        )
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        headers["Authorization"] = f"Bearer {token.token}"
        return headers

    def analyze(self, *, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> dict:
        if not self.configured:
            raise RuntimeError("Azure AI Foundry is not configured")

        body = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        req = request.Request(
            self._url(),
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)
