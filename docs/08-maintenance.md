# Maintenance

Documentation pending.

## Storage Health API

Installed on 2026-08-06.

- Service: `p2-health-api.service`
- API: `http://192.168.0.203:8787/api/storage`
- SMB health: `http://192.168.0.203:8787/health/smb`
- Checks:
  - Samba service status
  - Media mount status
  - Media free space
  - Family Vault mount status
  - Backup drive mount status

Useful commands:

```bash
sudo systemctl status p2-health-api --no-pager
curl http://127.0.0.1:8787/api/storage
sudo journalctl -u p2-health-api --since today --no-pager
```
