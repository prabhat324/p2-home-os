# Backup Strategy

## Backup priorities

Not all P² Home OS data has the same value.

### Tier 1 — irreplaceable

- private photos and family videos;
- personal documents;
- Project Osho YouTube upload receipts and durable job metadata;
- service configuration that is not reproducible from Git.

### Tier 2 — expensive to recreate

- transcripts;
- AI/application metadata;
- final Osho renders;
- Immich database/configuration;
- Home Assistant configuration and automations.

### Tier 3 — replaceable

- Jellyfin cache/transcodes;
- downloaded media that can be reacquired;
- temporary Osho work directories;
- container image layers.

## Photo backup design

- 3 TB drive: primary private photo library.
- 2 TB drive: designated backup target.

The 2 TB drive's **current mount and successful recurring-backup state have not been re-verified during the 2026-08-14 documentation audit**. Therefore this document does not claim that a current backup exists merely because the drive is designated for that purpose.

A backup is considered healthy only after verifying:

```text
source mounted
backup target mounted
latest job succeeded
file counts / checksums or equivalent verification passed
restore test succeeded
```

## compute-01 application backups

compute-01 has daily local application/config backup behavior documented in its as-built state. These backups protect configuration but do not replace an independent copy of private media/photos.

## Project Osho

Back up at minimum:

```text
/srv/osho/youtube/receipts
/srv/osho/metadata
/srv/osho/transcripts
```

Final renders are valuable but can often be regenerated if the source, transcript, metadata, and exact cut information survive.

## Configuration backup

GitHub is the source of truth for non-secret configuration and documentation. Secrets must remain outside Git and need a separate secure backup method.

Never commit:

```text
OAuth tokens
API keys
SSH private keys
password files
client secrets
Tailscale auth keys
```

## Verification cadence

At least weekly for irreplaceable data:

```bash
findmnt /mnt/photos-primary || true
findmnt /mnt/backup || true
df -h
systemctl --failed
```

Then inspect the actual backup job/log and periodically perform a test restore of several files.

## Rule

**A mounted backup disk is not a backup. A successful, verified, restorable copy is a backup.**
