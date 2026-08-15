# Storage Layout

The authoritative current storage documentation is [Storage Architecture](../04-storage.md).

## Current roles

```text
core-01:/mnt/media          8 TB media source
compute-01:/mnt/media       read-only NFS view of media
Immich:/mnt/photos-primary  read-only 3 TB private photo library
/srv/osho                   durable Project Osho state
```

The 2 TB private-photo backup target remains designated but should not be described as active until its mount and successful backup job are re-verified.

This page is intentionally concise to avoid maintaining a conflicting duplicate of the main storage document.
