"""Public export: lock scientific frozen bytes and v0.7 product files.

Scientific/evaluator/D-controller bytes are unchanged from public v0.4.0.
Identity kernel verification contracts and resolve adapter files remain locked
to private canonical source fafa3709c28fa9058f62bc9c2524e607e84a2fa3
(byte-identical with public v0.5/v0.6 identity slice).

v0.7 intentionally updates constrain API surface files (api/runtime/report/
session/__init__/errors) and adds governing/semantic/_v07_* hybrid packages
ported from private ea28dcfb9a132af780a016bc01d24fecd6f3eab0. Evaluator wall,
privacy, and ext remain unchanged from v0.6.
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
    "ai4/constrain/api.py": "ffc5c379a186955bb6db48d16b720e0423a80fca08bab8e23d538a77e3aab752",
    "ai4/constrain/runtime.py": "9e22e0f800ace1bcf291bd73d77473d1137584bbed039552b3ca475a7d810605",
    "ai4/constrain/report.py": "b41c269fc9dd020efa236ce4ee5f69a7467dd43714f24359a13cf4b89e670d73",
    "ai4/constrain/ext.py": "d22e02cc7693061427655847dd6131fd95a898092afacd509701de0a32b4d023",
    "ai4/constrain/session.py": "a0fb2d30abe197131990aaf129667526f4ceb3355e65e5113b2f8988ce20de29",
    "ai4/constrain/evaluator_wall.py": "f146713893745d64b0cf823f2ac9c3fa10bcccf0400d493d80dc2bcb458e308d",
    "ai4/constrain/privacy.py": "87e9eaf077b84e60813ef3e1142c29e9e0d38ccc2e42fe0fca9ceb9fd46ecb58",
    "ai4/constrain/__init__.py": "22c4de0c403640873ea68bd82728cf0f749681bda749c780241c054a93a5e3b8",
    "ai4/constrain/errors.py": "842ea7f07db8d99f89fc103908962e5838c0ad9235eeb709e046e972394cd14a",
    "ai4/constrain/governing.py": "ce689047703f4f7779feb8c962d4e21c38e1acc3949723ffa443a2309c76d499",
    "ai4/constrain/semantic_examiner.py": "d41baa89b434bc67e6192991f165435382ee6fc97d55753b50fc0ac9e788ea4d",
    "ai4/constrain/semantic_findings.py": "2fb245f6fa0e48d5b3366ea0191afbd0b35c3bea6666f79e1fe632e57cb2bcaa",
    "ai4/constrain/semantic_fuse.py": "1c7d68a9648eb717f98c4e3e1440fa7fc2d35e43505f5ce76ef253ffc545627e",
    "ai4/constrain/semantic_taxonomy.py": "981391ce142f73527f2d7debeeced820939d012498f5726f8ab8620da8befcc0",
    "ai4/data/semantic_v07/finding_registry_v1.json": "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535",
    "ai4/data/semantic_v07/finding_policy_map_v1.json": "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78",
    "ai4/data/semantic_v07/observation_prompt_v1.txt": "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf",
    "ai4/constrain/_v07_3a/__init__.py": "7d1440160d14e32532ca64c648964863fd0aa5b2e16883a0e5c50c24ac937ee7",
    "ai4/constrain/_v07_3a/_common.py": "f59a4c13cb7632c12b1a0eefd167da8efe0cbc2230ed8c01ced34aa71b7668e9",
    "ai4/constrain/_v07_3a/abort.py": "e64ea7ff9e5fd88907e85ca07e80e816d7c8a4bccd3f444ba3ec78538ae7a6a9",
    "ai4/constrain/_v07_3a/budget.py": "d012e117ef99af838ba5f3638d07a01c29f615e2b08bccffe53ee37722ebfec6",
    "ai4/constrain/_v07_3a/context.py": "0715a119fdf9ac36912edacb572d37ee0405dabf214b623f73afd87f845bda86",
    "ai4/constrain/_v07_3a/continuity.py": "e7c702511908f083fe8d42ee0d7be443b82f5fb85bc1443377c313e597dc8e29",
    "ai4/constrain/_v07_3a/rebuild.py": "56e1ffdcae0bf28050fc5012a8d0bb8dbfafa933589f3c70805f1405ffd06405",
    "ai4/constrain/_v07_3a/report.py": "8e96d22fc6cb969b6451566547e6dfd14e0cea9a1909c128a8f017037ef6af9d",
    "ai4/constrain/_v07_3b/__init__.py": "b9aea99cea399fa7dbf5b328b38d5194303f501f7cb694855c53fc804d39d5f5",
    "ai4/constrain/_v07_3b/budget.py": "84ce6d5ab55e644ae9e2de126c8f90a95e92495eca0994e4806ed6f160e65a60",
    "ai4/constrain/_v07_3b/context.py": "468d4c5716c3fc2ad36c5b800ee77e226a927842f3708dfe32fbc3be4a665fc0",
    "ai4/constrain/_v07_3b/feedback.py": "bdc87b9b5d704c91e7ea331a8ce20ce415ca8cf861ee18fe65572e26b53869a0",
    "ai4/constrain/_v07_3b/origin.py": "c9a4dcf935eb93348f508515bb77959ce95ea082fa0c2472e544b83076c1beaf",
    "ai4/constrain/_v07_3b/provenance.py": "ef43ea3f5405902beab1b2535913d9ea44fba39119a0f3a9a990bfdbf11fb96d",
    "ai4/constrain/_v07_3b/readiness.py": "7a3043ccea1039da5168bbcf0b4a0b9df9b29b98b6aaf180764d490ea1c5e067",
    "ai4/constrain/_v07_3b/report.py": "ef6b41ee5f1609f0fbca70aa59a8edaf2c29d6fa096a6eb75f1e2d49e8048de2",
    "ai4/constrain/_v07_3b/separation.py": "8d5084efc51cf6da9e857a489211db0bb9f6bb341c2e079803a8a8bfeb977084",
    "ai4/constrain/_v07_3b/session.py": "4fe0a6ff36731deccea7e95082cd1f7e8d601e8387d37edd55812204ebaebdb9",
    "ai4/constrain/_v07_3b/snapshot.py": "fb0d26ec7afd2b59957f84b33c280b8cc931e9ee6512ad1a996f787d0fb7c906",
    "ai4/constrain/_v07_3c/__init__.py": "6a4e9d9e2ce26b8bf19a605e84a5168d51cb5680975aa5b95e307cf87c49ef84",
    "ai4/constrain/_v07_3c/entry.py": "c71ca21b7091b3ed932e4e5daab46a3658645dafa404d8cef20bd672a71e04f6",
    "ai4/constrain/_v07_3c/install.py": "6e2f370ff719d11b878635f71122c7b3fcc9bed0ce6401b1eda9151419008f7c",
    "ai4/constrain/_v07_3c/loop.py": "8e1f33d6348e9d3cf012b6c8f8dbfaa4d5519bc4884f1381265c9e43df768648",
    "ai4/constrain/_v07_3c/observe.py": "6d3897ea4caaef5a330c734584d64de54cdebed6210b57b06b024477c00a384d",
    "ai4/constrain/_v07_3c/persist.py": "42aef4c75ec4702db93068677c58426711279ae69a8b8b7a19584f2a5e8265f3",
    "ai4/constrain/_v07_3c/ready.py": "24abf7fbfc27149a6fe28303200940e8b1c4386f19bf9b79cb935fc8e6e77de6",
    "ai4/constrain/_v07_3c/report.py": "e400b5683db6c0eba61f997f56ef1d9cd948a8f35b43119248895cb982d1a5b9",
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
