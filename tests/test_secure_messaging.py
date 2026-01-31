"""Tests for swarm.secure_messaging."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm import secure_messaging as sm


def _build_protocol():
    protocol = sm.SecureMessagingProtocol()
    protocol._sessions.clear()
    protocol._audit_logs.clear()
    protocol._replay_cache.seen_nonces.clear()
    return protocol


def test_session_binding_and_token_verification():
    protocol = _build_protocol()
    session = protocol.establish_mtls_session(
        client_cert_fingerprint="client123",
        server_cert_fingerprint="server456",
        session_key="key789",
    )

    token_binding_id = protocol.bind_token_to_session(session.session_id, token="jwt-token")
    assert token_binding_id == session.token_binding_id

    message = protocol.create_message(
        message_type=sm.MessageType.REQUEST,
        sender_did="did:agent:alpha",
        recipient_did="did:agent:beta",
        payload={"cmd": "ping"},
        session_id=session.session_id,
    )

    verified, reason = protocol.verify_message(message, session.session_id)
    assert verified is True
    assert reason == "Message verified"


def test_replay_and_age_protection():
    protocol = _build_protocol()

    session = protocol.establish_mtls_session("c", "s", "k")
    protocol.bind_token_to_session(session.session_id, "token")

    message = protocol.create_message(
        sm.MessageType.EVENT,
        sender_did="did:agent:event",
        recipient_did="did:agent:listener",
        payload={"payload": True},
        session_id=session.session_id,
    )

    message.timestamp = datetime.utcnow() - timedelta(seconds=1000)
    verified, reason = protocol.verify_message(message, session.session_id)
    assert verified is False
    assert "too old" in reason.lower()

    message.timestamp = datetime.utcnow()
    message.nonce = "nonce-123"
    message.signature = protocol._sign_message(message)
    verified, _ = protocol.verify_message(message, session.session_id)
    assert verified is True

    replayed = sm.MessageEnvelope(
        message_id=message.message_id,
        message_type=message.message_type,
        sender_did=message.sender_did,
        recipient_did=message.recipient_did,
        payload=message.payload,
        nonce="nonce-123",
        session_id=session.session_id,
    )
    replayed.signature = protocol._sign_message(replayed)
    verified, reason = protocol.verify_message(replayed, session.session_id)
    assert verified is False
    assert "replay" in reason.lower()


def test_send_and_receive_create_audit_logs():
    protocol = _build_protocol()
    session = protocol.establish_mtls_session("client", "server", "key")
    protocol.bind_token_to_session(session.session_id, "token")

    message = protocol.create_message(
        message_type=sm.MessageType.RESPONSE,
        sender_did="did:agent:responder",
        recipient_did="did:agent:requester",
        payload={"ok": True},
        session_id=session.session_id,
    )

    send_log = protocol.send_message(message, session.session_id)
    assert send_log.status == "sent"
    assert send_log.signature_verified is True

    protocol._replay_cache.seen_nonces.clear()
    recv_verified, recv_reason, payload = protocol.receive_message(message, session.session_id)
    assert recv_verified is True
    assert payload == message.payload

    assert len(protocol._audit_logs) >= 2
    statuses = {log.status for log in protocol._audit_logs}
    assert "sent" in statuses and "delivered" in statuses


def test_verify_message_detects_token_binding_mismatch():
    protocol = _build_protocol()
    session = protocol.establish_mtls_session("client", "server", "key")
    protocol.bind_token_to_session(session.session_id, "token")

    message = protocol.create_message(
        message_type=sm.MessageType.REQUEST,
        sender_did="did:agent:a",
        recipient_did="did:agent:b",
        payload={"op": "sync"},
        session_id=session.session_id,
    )

    message.token_binding_id = "invalid-binding"
    verified, reason = protocol.verify_message(message, session.session_id)
    assert verified is False
    assert "token binding" in reason.lower()


def test_send_message_rejects_invalid_signature():
    protocol = _build_protocol()
    session = protocol.establish_mtls_session("client", "server", "key")
    protocol.bind_token_to_session(session.session_id, "token")

    message = protocol.create_message(
        message_type=sm.MessageType.REQUEST,
        sender_did="did:agent:a",
        recipient_did="did:agent:b",
        payload={"action": "invalid"},
        session_id=session.session_id,
    )

    message.signature = "bogus"
    log = protocol.send_message(message, session.session_id)
    assert log.status == "rejected"
    assert "signature" in log.error_message.lower()
