#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=runner.env
source "${SCRIPT_DIR}/runner.env"
# shellcheck source=versions.env
source "${SCRIPT_DIR}/versions.env"

fail() {
  printf 'runner_registration_error=%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail root_required
grep -Fxq 'CLASSIFICATION=NON_PRODUCTION' /etc/ci-runner-host-classification \
  || fail host_not_classified_non_production
id "${CI_RUNNER_USER}" >/dev/null 2>&1 || fail runner_user_missing
[[ "${CI_RUNNER_NAME}" =~ ^[A-Za-z0-9._-]+$ ]] || fail invalid_runner_name
[[ "${CI_RUNNER_LABELS}" =~ ^[A-Za-z0-9._,-]+$ ]] || fail invalid_runner_labels
[[ "${CI_GITHUB_REPOSITORY_URL}" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] \
  || fail invalid_repository_url

runner_uid="$(id -u "${CI_RUNNER_USER}")"
runner_env=(
  "HOME=${CI_RUNNER_HOME}"
  "USER=${CI_RUNNER_USER}"
  "LOGNAME=${CI_RUNNER_USER}"
  "XDG_RUNTIME_DIR=/run/user/${runner_uid}"
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${runner_uid}/bus"
)

run_as_runner() {
  runuser -u "${CI_RUNNER_USER}" -- env "${runner_env[@]}" "$@"
}

rootless_socket="unix:///run/user/${runner_uid}/docker.sock"
run_as_runner env "DOCKER_HOST=${rootless_socket}" docker info >/dev/null 2>&1 \
  || fail rootless_docker_unavailable

install -d -m 0755 "${GITHUB_RUNNER_DOWNLOAD_CACHE}"
archive="${GITHUB_RUNNER_DOWNLOAD_CACHE}/actions-runner-linux-x64-${GITHUB_RUNNER_VERSION}.tar.gz"
if [[ ! -f "${archive}" ]] || ! printf '%s  %s\n' "${GITHUB_RUNNER_SHA256}" "${archive}" | sha256sum --check --strict >/dev/null 2>&1; then
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf -- "${tmp_dir}"' EXIT
  candidate="${tmp_dir}/actions-runner.tar.gz"
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "${candidate}" \
    "https://github.com/actions/runner/releases/download/v${GITHUB_RUNNER_VERSION}/actions-runner-linux-x64-${GITHUB_RUNNER_VERSION}.tar.gz"
  printf '%s  %s\n' "${GITHUB_RUNNER_SHA256}" "${candidate}" | sha256sum --check --strict
  install -o root -g root -m 0644 "${candidate}" "${archive}"
  rm -rf -- "${tmp_dir}"
  trap - EXIT
fi

if [[ ! -x "${CI_RUNNER_DIR}/bin/Runner.Listener" ]]; then
  if find "${CI_RUNNER_DIR}" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail runner_directory_not_empty
  fi
  tar -xzf "${archive}" -C "${CI_RUNNER_DIR}"
  chown -R "${CI_RUNNER_USER}:${CI_RUNNER_USER}" "${CI_RUNNER_DIR}"
fi

installed_version="$(run_as_runner "${CI_RUNNER_DIR}/bin/Runner.Listener" --version)"
[[ "${installed_version}" == "${GITHUB_RUNNER_VERSION}" ]] || fail unexpected_runner_version

if [[ ! -f "${CI_RUNNER_DIR}/.runner" ]]; then
  RUNNER_REGISTRATION_TOKEN="${RUNNER_REGISTRATION_TOKEN:-}"
  RUNNER_REGISTRATION_TOKEN="${RUNNER_REGISTRATION_TOKEN%$'\r'}"
  [[ -n "${RUNNER_REGISTRATION_TOKEN}" ]] || fail registration_token_required
  [[ "${RUNNER_REGISTRATION_TOKEN}" =~ ^[A-Za-z0-9]+$ ]] || fail invalid_registration_token
  run_as_runner bash -lc \
    "cd '${CI_RUNNER_DIR}' && ./config.sh --unattended --replace --disableupdate \
      --url '${CI_GITHUB_REPOSITORY_URL}' \
      --token '${RUNNER_REGISTRATION_TOKEN}' \
      --name '${CI_RUNNER_NAME}' \
      --labels '${CI_RUNNER_LABELS}' \
      --work '_work'"
fi

[[ -f "${CI_RUNNER_DIR}/.runner" ]] || fail runner_registration_not_persisted

install -d -o root -g root -m 0755 "${CI_CONFIG_DIR}"
cat > "${CI_ENV_FILE}" <<EOF
DOCKER_HOST=${rootless_socket}
RUNNER_TOOL_CACHE=${CI_RUNNER_CACHE}/toolcache
AGENT_TOOLSDIRECTORY=${CI_RUNNER_CACHE}/toolcache
DISABLE_RUNNER_UPDATE=1
EOF
chown root:root "${CI_ENV_FILE}"
chmod 0644 "${CI_ENV_FILE}"

if [[ ! -f "/etc/systemd/system/${CI_RUNNER_SERVICE}" ]]; then
  (
    cd "${CI_RUNNER_DIR}"
    ./svc.sh install "${CI_RUNNER_USER}"
  )
fi
[[ -f "/etc/systemd/system/${CI_RUNNER_SERVICE}" ]] || fail unexpected_service_name

override_dir="/etc/systemd/system/${CI_RUNNER_SERVICE}.d"
install -d -o root -g root -m 0755 "${override_dir}"
cat > "${override_dir}/50-ci-hardening.conf" <<EOF
[Service]
EnvironmentFile=${CI_ENV_FILE}
ExecStartPre=/usr/bin/test -S /run/user/${runner_uid}/docker.sock
CPUQuota=${CI_RUNNER_CPU_QUOTA}
MemoryHigh=${CI_RUNNER_MEMORY_HIGH}
MemoryMax=${CI_RUNNER_MEMORY_MAX}
TasksMax=${CI_RUNNER_TASKS_MAX}
OOMPolicy=stop
TimeoutStopSec=5min
UMask=0027
NoNewPrivileges=true
CapabilityBoundingSet=
AmbientCapabilities=
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectClock=true
ProtectHostname=true
LockPersonality=true
RestrictRealtime=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
SystemCallArchitectures=native
ReadWritePaths=/srv/ci
InaccessiblePaths=/root
EOF
chown root:root "${override_dir}/50-ci-hardening.conf"
chmod 0644 "${override_dir}/50-ci-hardening.conf"

systemctl daemon-reload
systemctl enable --now "${CI_RUNNER_SERVICE}"
systemctl is-active --quiet "${CI_RUNNER_SERVICE}" || fail runner_service_inactive

printf 'registration_status=ok\n'
printf 'runner_name=%s\n' "${CI_RUNNER_NAME}"
printf 'runner_version=%s\n' "${installed_version}"
printf 'service=%s\n' "${CI_RUNNER_SERVICE}"
