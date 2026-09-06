# P2 Media Handoff Workflow

## Purpose

Use `storage-01` as the durable handoff point between Prabhat's Mac and P2 media workers while keeping rendering and temporary work on worker-local SSD/NVMe.

## NAS location

SMB share:

```text
smb://192.168.0.53/Web/YouTube Dump/Prabhat
```

Required directories:

```text
YouTube Dump/Prabhat/
├── INBOX/
│   └── <project>/
└── OUTBOX/
    └── <project>/
```

Workers mount the `Web` share at:

```text
/mnt/p2-nas-web
```

The project handoff root therefore resolves to:

```text
/mnt/p2-nas-web/YouTube Dump/Prabhat
```

## Worker flow

1. Prabhat places source material in `INBOX/<project>/` from the Mac.
2. A worker stages the project to local SSD with `p2-media-intake <project>`.
3. Processing happens only in `/srv/media-production/work/<project>/`.
4. Intermediate files belong in `scratch/`; final candidate files belong in `final/`.
5. `p2-media-publish <project> <final-file>` validates the media with `ffprobe`, copies it to NAS using a temporary `.partial` file, verifies SHA-256, atomically renames it into `OUTBOX/<project>/`, and writes sidecar checksum and ffprobe metadata.
6. Prabhat visually reviews the OUTBOX copy from the Mac.
7. After explicit approval, `p2-media-signoff <project>` marks the local managed workspace for removal after a 24-hour grace period.

## Local workspace

```text
/srv/media-production/work/<project>/
├── .p2-managed
├── .staged_at
├── input/
├── scratch/
├── final/
└── logs/
```

`p2-media-intake` refuses to overwrite an existing local project that is not marked `.p2-managed`.

## Housekeeping

`p2-media-clean-stale.timer` runs daily.

Safety rules:

- Only `.p2-managed` workspaces are touched.
- Active workspaces referenced by running processes are skipped.
- Scratch files and `.partial`/`.tmp` files older than 7 days are removed.
- Whole workspaces are not automatically removed merely because they are old.
- A signed-off workspace is removed after a 24-hour grace period.
- An explicitly abandoned workspace is removed after 7 days.
- NAS INBOX and OUTBOX content is never automatically deleted by worker housekeeping.

## SMB security

Use a dedicated NAS account such as `p2media`. Prefer read/write access only to `Web/YouTube Dump/Prabhat` using QNAP advanced folder permissions. Do not store a NAS administrator password on workers.

Worker credentials are stored locally at:

```text
/etc/p2-media-smb.creds
```

with root-only mode `0600` and are referenced by the systemd CIFS mount unit. Credentials are not stored in Git.

## Worker commands

```bash
p2-media-nas-check
p2-media-intake PROJECT
p2-media-publish PROJECT /path/to/final.mp4
p2-media-signoff PROJECT
```

## Design principle

The NAS is the durable exchange and review surface. It is not the render scratch disk. Large 4K processing should use the worker's local SSD/NVMe and only copy source/final assets across SMB.