"""Public export: lock scientific frozen bytes and v0.3 product files.

Scientific/evaluator/D-controller bytes are unchanged from public v0.2.0.
Product files api.py, runtime.py, and report.py are the v0.3 policy-wall
port; ext.py and session.py are locked because they implement that wall.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FROZEN_SHA256 = {
    "ai4/data/rubrics/v0.1/autonomy.yaml": "8db919759fae52d75945056c0e5cd5c3a9250a0a2485bc3d725bc5ef20e585a4",
    "ai4/data/rubrics/v0.1/privacy.yaml": "adfa12df37b6b2d2c68ebc14059f95a33b29f09752b242dadd562a5fce58628e",
    "ai4/data/rubrics/v0.1/compassion.yaml": "ba97d64b87de83b47b053ac21ea9ff9ea3771919b26b7f18bb913bf5bd3e0db6",
    "ai4/data/rubrics/v0.1/harm_aversion.yaml": "603f4e093094331f5f7d758679b2500ef5119f946cce8d9ed095150bf66d036f",
    "ai4/data/rubrics/v0.1/truth.yaml": "a92d73e6820a6ae567c43c0e470aaff7aee6afab9ac388d875269c52c7687c3c",
    "rubrics/v0.1/autonomy.yaml": "8db919759fae52d75945056c0e5cd5c3a9250a0a2485bc3d725bc5ef20e585a4",
    "rubrics/v0.1/privacy.yaml": "adfa12df37b6b2d2c68ebc14059f95a33b29f09752b242dadd562a5fce58628e",
    "rubrics/v0.1/compassion.yaml": "ba97d64b87de83b47b053ac21ea9ff9ea3771919b26b7f18bb913bf5bd3e0db6",
    "rubrics/v0.1/harm_aversion.yaml": "603f4e093094331f5f7d758679b2500ef5119f946cce8d9ed095150bf66d036f",
    "rubrics/v0.1/truth.yaml": "a92d73e6820a6ae567c43c0e470aaff7aee6afab9ac388d875269c52c7687c3c",
    "src/shards/arbitration.py": "84644aa2cf0b7d00b4e5960029886a55bca3e4653e2a4e3d34818d357b9d77f4",
    "src/shards/shard_evaluator.py": "bf30a7c9ac629b576f987d42419e3c1cdc1e1fc26d90ba51e12c3074d7a61c7c",
    "src/shards/shard_loader.py": "fa059f4c31a32d02ea70f38b83881050da5e0bb9dd3c358f17f2cd4a74aa439e",
    "src/shards/models.py": "65f05a27d850f36b2e762a98e9c40a66d5c03c9b0b6cd1675a7df3a72286801d",
    "src/constraints/constraint_middleware.py": "0432933bac4adde9ba555fbb6dce478ae8450b7eb32c5e6ce0f0d7512b0dca41",
    "src/agents/recursive_agent.py": "ba8e53bedd3acd6d230b236ac524bb0f1f386eca861cae64c5ec6c099de70859",
    "ai4/constrain/api.py": "c77b6e602e4de9451fdf03e3380906f41f0ac3c0fd81390433c28089957eb50a",
    "ai4/constrain/runtime.py": "aebe5604384b700b0be1a706d8e5ed05c8a28573c7afbd1d3f63473eed09029c",
    "ai4/constrain/report.py": "a53733346642999a4a72089bf653269680b960cfaba862a5294991526e7c3e76",
    "ai4/constrain/ext.py": "4abc9dd1b2c8c7fd9df284cf4be1f7728314060baba578757d677958d30ec5a4",
    "ai4/constrain/session.py": "3a2693fa2d7d2e056b24bbfc0877b9e32faaa991caa278d31ed1d8d855e12bb6",
    "ai4/constrain/privacy.py": "87e9eaf077b84e60813ef3e1142c29e9e0d38ccc2e42fe0fca9ceb9fd46ecb58",
    "docs/protocol-v0.1.md": "e55a00f81701efa181eec65a9c67a94b077575796b850ad9eee47bea30c83ca7",
}


def test_public_runtime_frozen_bytes_match_export_lock():
    root = Path(__file__).resolve().parents[1]
    for rel, expected in FROZEN_SHA256.items():
        data = (root / rel).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == expected, f"{rel} drifted ({digest})"
