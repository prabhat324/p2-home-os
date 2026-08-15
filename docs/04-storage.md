# Storage Architecture

## 8 TB media storage

- Device: Seagate Expansion Desktop 8 TB
- Physical host: `core-01` / `media-server`
- Mount point: `/mnt/media`
- Purpose: Jellyfin media and general family-accessible media storage

compute-01 consumes the library read-only over NFSv4.2:

```text
192.168.0.203:/mnt/media -> /mnt/media
```

This keeps the disk physically attached to the always-on storage node while moving Jellyfin transcoding and application work to the GPU node.

## 3 TB private photo storage

The 3 TB drive is the private primary photo library.

Confirmed Immich view:

```text
/mnt/photos-primary
```

Inside Immich the mount is read-only, protecting the original photo library from application-side deletion or modification.

The source drive has contained legacy material under directories such as `Old Images on Drive`; existing source structure should not be reorganized casually during indexing.

## 2 TB backup storage

The 2 TB WD drive is reserved for backup of the private photo library.

Current documentation status: **designated, but active mount/scheduled-backup state has not been re-verified in this documentation pass.** Do not claim backup coverage until a current mount and successful backup run are verified.

## Project Osho data

Durable Project Osho state belongs under:

```text
/srv/osho
```

Application code/configuration is under:

```text
/srv/compose/osho-worker
```

Keep durable job state, transcripts, renders, metadata, and YouTube receipts separate from application code.

## Storage principles

- Original/private photos should be mounted read-only into photo-management applications where practical.
- Media can be replaceable; private photos and publishing receipts are not.
- Backups must be verified, not inferred from a mounted disk.
- Prefer stable mount points over `/dev/sdX` names.
- Before formatting or repurposing a drive, verify source and destination file counts/sizes and retain a second copy until validation is complete.

## Verification commands

```bash
findmnt /mnt/media
findmnt /mnt/photos-primary || true
df -h /mnt/media /mnt/photos-primary 2>/dev/null || true
lsblk -f
```
