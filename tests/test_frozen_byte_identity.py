"""Public export: lock scientific frozen bytes and v0.6 product files.

Scientific/evaluator/D-controller bytes are unchanged from public v0.4.0.
Constrain product files api.py, report.py, ext.py, session.py,
evaluator_wall.py, runtime.py, and privacy.py are unchanged: identity is a
sibling kernel and must not edit the governing constrain path.
Identity kernel verification contracts (schemas, attestation, trust, binding)
remain locked to private canonical source
fafa3709c28fa9058f62bc9c2524e607e84a2fa3 (byte-identical with public v0.5).
PR-F resolve adapter files and the identity preamble/docs that point at that
sibling are locked to the same private source.
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
    "ai4/constrain/api.py": "c26d2fe1d0526da59435085ec4ef6fe3f2f5c22a4cd9ef62f26595fd3c1d1a41",
    "ai4/constrain/runtime.py": "aebe5604384b700b0be1a706d8e5ed05c8a28573c7afbd1d3f63473eed09029c",
    "ai4/constrain/report.py": "51748a6620c1af7135c2bb89eb928fbe858914039e3c9f98f912ad5548a8aca8",
    "ai4/constrain/ext.py": "d22e02cc7693061427655847dd6131fd95a898092afacd509701de0a32b4d023",
    "ai4/constrain/session.py": "f18650d13c58b73101d43cedeed555c6d130c6175503bb8a0fb27cac359ca596",
    "ai4/constrain/evaluator_wall.py": "f146713893745d64b0cf823f2ac9c3fa10bcccf0400d493d80dc2bcb458e308d",
    "ai4/constrain/privacy.py": "87e9eaf077b84e60813ef3e1142c29e9e0d38ccc2e42fe0fca9ceb9fd46ecb58",
    "docs/protocol-v0.1.md": "e55a00f81701efa181eec65a9c67a94b077575796b850ad9eee47bea30c83ca7",
    "ai4/identity/__init__.py": "7aacf45b465eabb38f84618ec0355ef4f1e2db57eac744032c2da8df9e03457d",
    "ai4/identity/__main__.py": "cb40cee7990bce45f54de048c12eef740ecd591cb911a88df6a8a6a53a1ff6ee",
    "ai4/identity/attestation.py": "a12b1d7b1e17ea73b94d3a3122f1688847ee55af6050dc1ea6fec28786f29782",
    "ai4/identity/binding.py": "949604596879ad07803e2d2d79802c50d30bfc53a0c61195b73077ccb621c7e1",
    "ai4/identity/canonical.py": "b8ed16069bde39252da29c30f2d67787ddaa4257aa390eb0beaaf0a8a2d75579",
    "ai4/identity/crypto.py": "69346acdf84b3763a59178741e8943ce3a5237f43668123bafc4bbdb0b0797ed",
    "ai4/identity/digest.py": "3e1a0160cc7729c1d293fc4dabe42db7f707997398cd1fcf3e81c5a3a138c930",
    "ai4/identity/errors.py": "70cf86d278f087899576243811b66a00f761ed48f426eeb876d2f0cf6e0ed045",
    "ai4/identity/py.typed": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "ai4/identity/schemas.py": "7a449ff0eb5ce1710408c40f3165d356af94d8e6c79d3166051ba9b107104b7b",
    "ai4/identity/timeutil.py": "cb509b30e364fd5c8c0f1b1e6b4997a7bcebaabef369f3cd81a0058e22e17eb5",
    "ai4/identity/trust.py": "bfa378007aaf1da8fa1ec477da5210b27da92f4ec4b41d4b1f9c7e69fe3621bf",
    "ai4/identity/resolve/__init__.py": "029675aed71160c576b786e1bc42e4a623a733b754649e258c8ed88e04938b56",
    "ai4/identity/resolve/cli.py": "bb01e3b597142420a0674a678a4868ca7a4903910bf6ce1b84f0bcf09afd96e2",
    "ai4/identity/resolve/fetch.py": "0f8565a6ac9d0163b4e11d8a4094d06ec524f4442cf89222f50fa4dfd2f0e9f3",
    "ai4/identity/resolve/file_resolver.py": "89661311cf60174c76d0940b8a4088c3e5aa6c5516e86933cff6a8bd97f1e4fe",
    "ai4/identity/resolve/pipeline.py": "45e3d32778a7d5a40998737095072db6341d3df50e926db033df7c4cdc14121b",
    "ai4/identity/resolve/resolver.py": "0fee9fd65e64618ce2d6733ba822160e5c25ea20d6d1d36df8a3eea66a9df31e",
    "ai4/identity/resolve/types.py": "347400927f86ae73d828ff8de789afe46c443de29e8be7971626e2f360409f68",
    "docs/identity.md": "1fd7dd111ffb9b9069318d5d713f950ea3ed1346651da0076a9c9aae89b6cf61",
    "docs/identity-resolution.md": "3dfe879ff4d9a5db4dcca739067318ed181909966c6b2ba3c58ae6db834b1d52",
}


def test_public_runtime_frozen_bytes_match_export_lock():
    root = Path(__file__).resolve().parents[1]
    for rel, expected in FROZEN_SHA256.items():
        data = (root / rel).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == expected, f"{rel} drifted ({digest})"
