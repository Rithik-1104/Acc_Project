import asyncio
import httpx
from typing import Optional
from backend.consensus.models import (
    RequestVoteArgs, RequestVoteReply,
    AppendEntriesArgs, AppendEntriesReply
)

class RaftRPCClient:
    """
    Async HTTP client for dispatching Raft consensus RPCs to peer nodes.
    Supports fault-injection network isolation at the transport layer.
    """
    def __init__(self, timeout_ms: int = 400):
        self.timeout = timeout_ms / 1000.0
        self._client: Optional[httpx.AsyncClient] = None
        self.is_isolated: bool = False

    def isolate(self) -> None:
        """Drop outgoing RPC packets."""
        self.is_isolated = True

    def heal(self) -> None:
        """Restore outgoing RPC communication."""
        self.is_isolated = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send_request_vote(self, peer_url: str, args: RequestVoteArgs) -> Optional[RequestVoteReply]:
        if self.is_isolated:
            return None
        url = f"{peer_url.rstrip('/')}/raft/request_vote"
        try:
            client = await self._get_client()
            resp = await client.post(url, json=args.model_dump())
            if resp.status_code == 200:
                return RequestVoteReply.model_validate(resp.json())
        except Exception:
            pass
        return None

    async def send_append_entries(self, peer_url: str, args: AppendEntriesArgs) -> Optional[AppendEntriesReply]:
        if self.is_isolated:
            return None
        url = f"{peer_url.rstrip('/')}/raft/append_entries"
        try:
            client = await self._get_client()
            resp = await client.post(url, json=args.model_dump())
            if resp.status_code == 200:
                return AppendEntriesReply.model_validate(resp.json())
        except Exception:
            pass
        return None
