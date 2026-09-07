"""Live on-hand quantities from the store's Admin API, read-only. Standard library
only. Credentials come from an env file (SHOPIFY_STORE, SHOPIFY_CLIENT_ID,
SHOPIFY_CLIENT_SECRET, optional SHOPIFY_ADMIN_API_VERSION); the same file the
companion recommender uses. Without one, callers proceed with stock unknown."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_API_VERSION = "2025-07"
INVENTORY_QUERY = """
query($cursor: String) {
  productVariants(first: 250, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node { id inventoryQuantity inventoryItem { unitCost { amount } } } }
  }
}"""


def read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class ShopifyAdmin:
    def __init__(self, store: str, client_id: str, client_secret: str, api_version: str = DEFAULT_API_VERSION):
        self.store, self.client_id, self.client_secret, self.api_version = store, client_id, client_secret, api_version
        self._token: str | None = None
        self._expiry = 0.0

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "ShopifyAdmin":
        missing = [k for k in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET") if not env.get(k)]
        if missing:
            raise ValueError(f"missing {', '.join(missing)} in env file")
        return cls(env["SHOPIFY_STORE"], env["SHOPIFY_CLIENT_ID"], env["SHOPIFY_CLIENT_SECRET"],
                   env.get("SHOPIFY_ADMIN_API_VERSION") or DEFAULT_API_VERSION)

    def _post(self, url: str, data: bytes, headers: dict[str, str]) -> dict:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    def _access_token(self) -> str:
        if self._token and time.time() < self._expiry - 300:
            return self._token
        body = self._post(f"https://{self.store}/admin/oauth/access_token",
                          urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self.client_id,
                                                  "client_secret": self.client_secret}).encode(),
                          {"Content-Type": "application/x-www-form-urlencoded"})
        if "access_token" not in body:
            raise RuntimeError(f"token exchange failed: {body.get('error_description') or body.get('error')}")
        self._token = body["access_token"]
        self._expiry = time.time() + float(body.get("expires_in", 86399))
        return self._token

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        for attempt in range(6):
            body = self._post(f"https://{self.store}/admin/api/{self.api_version}/graphql.json",
                              json.dumps({"query": query, "variables": variables or {}}).encode(),
                              {"Content-Type": "application/json", "X-Shopify-Access-Token": self._access_token()})
            errors = body.get("errors") or []
            if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                time.sleep(2.0 * (attempt + 1))
                continue
            if errors:
                raise RuntimeError(f"GraphQL error: {errors[0].get('message')}")
            return body["data"]
        raise RuntimeError("throttled by Shopify too many times in a row")


def fetch_inventory(api: ShopifyAdmin) -> tuple[dict[str, int], dict[str, float]]:
    """On-hand quantity per variant id (string tail of the gid), and the store's
    "cost per item" where it is set. Needs read_inventory."""
    qty: dict[str, int] = {}
    cost: dict[str, float] = {}
    cursor = None
    while True:
        page = api.graphql(INVENTORY_QUERY, {"cursor": cursor})["productVariants"]
        for edge in page["edges"]:
            n = edge["node"]
            vid = n["id"].rsplit("/", 1)[-1]
            qty[vid] = int(n.get("inventoryQuantity") or 0)
            uc = (n.get("inventoryItem") or {}).get("unitCost")
            if uc and uc.get("amount") is not None:
                cost[vid] = float(uc["amount"])
        if not page["pageInfo"]["hasNextPage"]:
            return qty, cost
        cursor = page["pageInfo"]["endCursor"]
