# Systemd unit files for MathVault automatic sync.
#
# Install (on the Ubuntu host):
#   sudo cp systemd/mathvault-update.service /etc/systemd/system/
#   sudo cp systemd/mathvault-update.timer  /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now mathvault-update.timer
#
# View status:
#   systemctl status mathvault-update.timer
#   journalctl -u mathvault-update.service -n 200
