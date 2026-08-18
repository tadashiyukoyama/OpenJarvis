"""Backward-compatible import for the WhatsApp domain store."""

from openjarvis.channels.whatsapp.store import WhatsAppStore, default_database_path

__all__ = ["WhatsAppStore", "default_database_path"]
