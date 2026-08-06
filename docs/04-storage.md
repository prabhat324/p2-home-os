# Storage Architecture

## Current Media Drive

- Device: Seagate Expansion Desktop
- Capacity: approximately 8 TB
- Linux device: `/dev/sda2`
- Mount point: `/mnt/media`
- Filesystem: NTFS
- Approximate usage at initial setup: 716 GB used
- Purpose: replaceable entertainment media and general storage

## Current Media Folders

- `/mnt/media/Movies`
- `/mnt/media/TV Shows`
- `/mnt/media/Music`
- `/mnt/media/Private Movies`
- `/mnt/media/Collections`
- `/mnt/media/Other`
- `/mnt/media/Downloads`
- `/mnt/media/Documentaries`
- `/mnt/media/Open Movies`
- `/mnt/media/Public Domain Movies`
- `/mnt/media/Backups`

## Private Movies

- Host path: `/mnt/media/Private Movies`
- Jellyfin library access should be restricted by user permissions.
- For complete separation from watch history, use a dedicated Jellyfin user with access only to the private library.

## Planned Family Vault

- Device: WD My Passport 3 TB
- Planned mount point: `/mnt/family`
- Planned filesystem: ext4
- Purpose:
  - Photos
  - Family videos
  - Documents
  - Phone backups
  - Immich data
  - Private archives

## Planned Backup Drive

- Device: WD 2 TB
- Planned mount point: `/mnt/backup`
- Planned filesystem: ext4
- Purpose: versioned backups of the Family Vault

## Planned Migration

1. Copy approximately 1 TB of existing photos from the 3 TB drive to a temporary directory on `/mnt/media`.
2. Verify file count, directory count and total size.
3. Format the 3 TB drive as ext4.
4. Mount it permanently at `/mnt/family`.
5. Restore the photos.
6. Install and validate Immich.
7. Format the 2 TB drive as ext4.
8. Mount it at `/mnt/backup`.
9. Create the first verified backup.
10. Keep the temporary 8 TB copy until all verification is complete.

# Storage Architecture

## Media Drive

- Device: Seagate Expansion 8 TB
- Mount point: `/mnt/media`
- Filesystem: NTFS
- Purpose: replaceable entertainment media

Important folders:

- `/mnt/media/Movies`
- `/mnt/media/TV Shows`
- `/mnt/media/Music`
- `/mnt/media/Private Movies`
- `/mnt/media/Downloads`
- `/mnt/media/Documentaries`
- `/mnt/media/Public Domain Movies`
- `/mnt/media/Backups`

## Planned Family Vault

- Device: WD My Passport 3 TB
- Planned mount point: `/mnt/family`
- Planned filesystem: ext4
- Purpose:
  - Photos
  - Family videos
  - Documents
  - Phone backups
  - Immich storage

## Planned Backup Drive

- Device: WD 2 TB
- Planned mount point: `/mnt/backup`
- Planned filesystem: ext4
- Purpose: backup of selected Family Vault data

## Migration Plan

1. Copy existing photos from the 3 TB drive to `/mnt/media/Photo Migration`.
2. Verify file count and total size.
3. Format the 3 TB drive as ext4.
4. Mount it at `/mnt/family`.
5. Restore the photos.
6. Install Immich.
7. Format and mount the 2 TB backup drive.
8. Create and verify the first backup.
