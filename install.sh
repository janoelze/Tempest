#!/bin/sh

set -e

REPO_URL="https://raw.githubusercontent.com/janoelze/Tempest/main"
INSTALL_DIR="${HOME}/.local/bin"

# Detect available download tool
if command -v curl >/dev/null 2>&1; then
    DOWNLOAD_CMD="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
    DOWNLOAD_CMD="wget -qO-"
else
    printf "Error: curl or wget required\n" >&2
    exit 1
fi

printf "Installing Tempest chat client and server...\n"

# Create install directory if it doesn't exist
mkdir -p "${INSTALL_DIR}"

# Download client
printf "Downloading client... "
if ${DOWNLOAD_CMD} "${REPO_URL}/client.py" > "${INSTALL_DIR}/tempest"; then
    chmod +x "${INSTALL_DIR}/tempest"
    printf "done\n"
else
    printf "failed\n"
    exit 1
fi

# Download server
printf "Downloading server... "
if ${DOWNLOAD_CMD} "${REPO_URL}/server.py" > "${INSTALL_DIR}/tempest-server"; then
    chmod +x "${INSTALL_DIR}/tempest-server"
    printf "done\n"
else
    printf "failed\n"
    exit 1
fi

printf "\nInstallation complete.\n\n"

printf "Usage:\n"
printf "  tempest [host:port]    Connect to server (default: localhost:1991)\n"
printf "  tempest-server [host] [port]  Start server (default: localhost:1991)\n\n"

printf "Chat commands:\n"
printf "  /connect <nickname>    Set your name\n"
printf "  /room <name>           Join a room\n"
printf "  /who                   List users in room\n"
printf "  /help                  Show help\n"
printf "  /bye                   Disconnect\n\n"

# Check if install dir is in PATH (POSIX compatible)
case ":${PATH}:" in
    *":${INSTALL_DIR}:"*) ;;
    *)
        printf "Warning: %s is not in your PATH\n" "${INSTALL_DIR}"
        printf "Add this to your shell profile:\n"
        printf "  export PATH=\"\${PATH}:%s\"\n\n" "${INSTALL_DIR}"
        printf "Or run directly: %s/tempest\n" "${INSTALL_DIR}"
        ;;
esac