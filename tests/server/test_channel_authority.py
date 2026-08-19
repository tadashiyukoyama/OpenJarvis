from openjarvis.server.channel_authority import (
    ACELERACHAT_MANAGED_CONNECTORS,
    ChannelAuthorityPolicy,
)


def test_vps_mode_assigns_email_and_whatsapp_exclusively_to_acelerachat() -> None:
    policy = ChannelAuthorityPolicy.from_env({"OPENJARVIS_CORE_MODE": "vps"})

    assert policy.blocked_connector_ids == ACELERACHAT_MANAGED_CONNECTORS
    assert policy.mount_legacy_customer_sources is False
    assert policy.public_status()["customer_channel_authority"] == "acelerachat"


def test_local_mode_preserves_legacy_connectors_for_compatibility() -> None:
    policy = ChannelAuthorityPolicy.from_env({"OPENJARVIS_CORE_MODE": "local"})

    assert policy.blocked_connector_ids == frozenset()
    assert policy.mount_legacy_customer_sources is True
