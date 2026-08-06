# Storage Layout

## Logical Storage Names

| Logical Name | Purpose | Physical Location |
|---|---|---|
| `media-01` | Movies, TV shows, music | 8 TB Seagate on core-01 |
| `family-01` | Primary family photos | Planned 3 TB WD drive |
| `backup-01` | Family-photo backup | Planned 2 TB WD drive |
| `compute-os` | Ubuntu Server and system files | 512 GB NVMe on compute-01 |
| `compute-cache` | AI models, transcodes, containers | 1 TB NVMe on compute-01 |

## Current Mount Points

- `/mnt/media`
- `/mnt/family`
- `/mnt/backup`

## Storage Principles

- Replaceable media is separated from irreplaceable family data.
- Family data must exist on at least two physical drives.
- Compute cache and transcode data are not treated as primary backups.
- Services must not start against empty mount-point directories.
- Storage health must be monitored before dependent services start.
