import os
from pydantic import BaseModel, Field

class RaftConfig(BaseModel):
    node_id: str = Field(..., description="Unique ID for this Raft node")
    bind_host: str = Field(default="0.0.0.0")
    port: int = Field(..., description="Port this node listens on")
    peers: dict[str, str] = Field(
        default_factory=dict,
        description="Map of peer node_id to base URL (e.g. {'node2': 'http://localhost:8002'})"
    )
    data_dir: str = Field(
        default="./data",
        description="Directory for durable WAL and metadata persistence"
    )
    
    # Configurable timers suitable for Docker Desktop on Windows
    heartbeat_interval_ms: int = Field(default=150, description="Leader heartbeat period in ms")
    election_timeout_min_ms: int = Field(default=600, description="Min election timeout in ms")
    election_timeout_max_ms: int = Field(default=1200, description="Max election timeout in ms")
    
    # Consensus network timeout
    rpc_timeout_ms: int = Field(default=400, description="RPC request timeout in ms")

def get_node_config_from_env() -> RaftConfig:
    node_id = os.getenv("RAFT_NODE_ID", "node1")
    port = int(os.getenv("RAFT_PORT", "8001"))
    data_dir = os.getenv("RAFT_DATA_DIR", f"./data/{node_id}")
    
    # Example peer mapping via environment
    # RAFT_PEERS="node1=http://raft-node-1:8001,node2=http://raft-node-2:8002,node3=http://raft-node-3:8003"
    raw_peers = os.getenv("RAFT_PEERS", "")
    peers: dict[str, str] = {}
    if raw_peers:
        for entry in raw_peers.split(","):
            if "=" in entry:
                pid, purl = entry.split("=", 1)
                if pid.strip() != node_id:
                    peers[pid.strip()] = purl.strip()
    else:
        # Default local development 3-node mapping
        default_cluster = {
            "node1": "http://127.0.0.1:8001",
            "node2": "http://127.0.0.1:8002",
            "node3": "http://127.0.0.1:8003"
        }
        peers = {k: v for k, v in default_cluster.items() if k != node_id}

    return RaftConfig(
        node_id=node_id,
        port=port,
        peers=peers,
        data_dir=data_dir
    )
