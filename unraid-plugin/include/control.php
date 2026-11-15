<?php
declare(strict_types=1);

const FLUXER_PLUGIN = '/usr/local/emhttp/plugins/fluxer';
const FLUXER_PROJECT = '/mnt/user/appdata/fluxer';
const FLUXER_LOG = '/var/log/fluxer-unraid.log';
const FLUXER_UPGRADE_PENDING = FLUXER_PROJECT . '-upgrades/pending';

ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('Pragma: no-cache');

function reply(array $body, int $status = 200): never
{
    http_response_code($status);
    echo json_encode($body, JSON_INVALID_UTF8_SUBSTITUTE | JSON_UNESCAPED_SLASHES);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    reply(['ok' => false, 'message' => 'This endpoint accepts POST requests only.'], 405);
}

$prepend = realpath('/usr/local/emhttp/webGui/include/local_prepend.php');
$included = array_filter(array_map('realpath', get_included_files()));
if (PHP_SAPI === 'cli' || !is_file('/etc/unraid-version') || $prepend === false || !in_array($prepend, $included, true)) {
    reply(['ok' => false, 'message' => 'This endpoint requires the Unraid web interface.'], 503);
}
// Unraid's auto-prepend validates CSRF before this file and removes the token.
if ((int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > 32768) {
    reply(['ok' => false, 'message' => 'The request is too large.'], 413);
}

function field(string $name): string
{
    $value = $_POST[$name] ?? '';
    if (!is_string($value)) {
        reply(['ok' => false, 'message' => 'The request contains an invalid field.'], 400);
    }
    return trim($value);
}

function command(array $arguments, int $timeout = 30): array
{
    $descriptors = [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
    $process = proc_open($arguments, $descriptors, $pipes, FLUXER_PLUGIN, null, ['bypass_shell' => true]);
    if (!is_resource($process)) {
        return [1, 'The controller could not start.'];
    }
    fclose($pipes[0]);
    stream_set_blocking($pipes[1], false);
    stream_set_blocking($pipes[2], false);
    $deadline = microtime(true) + $timeout;
    $text = '';
    $exit = -1;
    do {
        $text .= stream_get_contents($pipes[1]) . stream_get_contents($pipes[2]);
        $text = substr($text, -32768);
        $state = proc_get_status($process);
        if (!$state['running']) {
            $exit = $state['exitcode'];
            break;
        }
        if (microtime(true) >= $deadline) {
            proc_terminate($process);
            usleep(100000);
            $state = proc_get_status($process);
            if ($state['running']) {
                proc_terminate($process, 9);
            }
            $exit = 124;
            $text = 'The controller did not respond within 30 seconds.';
            break;
        }
        usleep(50000);
    } while (true);
    if ($exit !== 124) {
        $text .= stream_get_contents($pipes[1]) . stream_get_contents($pipes[2]);
    }
    fclose($pipes[1]);
    fclose($pipes[2]);
    $closed = proc_close($process);
    return [$exit >= 0 ? $exit : $closed, trim(substr($text, -32768))];
}

function helper(array $arguments): array
{
    $path = FLUXER_PLUGIN . '/scripts/fluxerctl';
    if (!is_file($path) || !is_executable($path)) {
        return [1, 'The controller is not installed.'];
    }
    return command(array_merge([$path], $arguments));
}

function releaseValue(mixed $value): ?string
{
    return is_string($value) && preg_match('/\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z/', $value) ? $value : null;
}

function backupId(mixed $value): ?string
{
    return is_string($value) && preg_match('/\Abackup-[A-Za-z0-9]{6}\z/', $value) ? $value : null;
}

function operationInfo(string $action): array
{
    [$code, $text] = helper([$action . '_info']);
    $info = $code === 0 ? json_decode($text, true) : null;
    $states = ['idle', 'unavailable', 'ready', 'running', 'completed', 'failed', 'interrupted'];
    if (!is_array($info) || !in_array($info['state'] ?? null, $states, true)) {
        $info = [
            'state' => 'unavailable',
            'message' => $action === 'upgrade' ? 'The upgrade status is not available.' : 'The controller cannot read the restore status.',
        ];
    }
    $requestId = $info['request_id'] ?? null;
    $status = [
        'available' => ($info['available'] ?? false) === true,
        'state' => $info['state'],
        'message' => is_string($info['message'] ?? null) ? $info['message'] : '',
        'phase' => is_string($info['phase'] ?? null) ? $info['phase'] : null,
        'request_id' => is_string($requestId) && preg_match('/\A[a-f0-9]{32}\z/', $requestId) ? $requestId : null,
    ];
    if ($action === 'upgrade') {
        $status['installed'] = releaseValue($info['installed'] ?? null);
        $status['target'] = releaseValue($info['target'] ?? null);
        $status['backup'] = is_string($info['backup'] ?? null) ? $info['backup'] : null;
        $status['available'] = $status['available'] && $status['target'] !== null;
        return $status;
    }

    $backups = [];
    foreach (is_array($info['backups'] ?? null) ? $info['backups'] : [] as $backup) {
        if (!is_array($backup)) {
            continue;
        }
        $id = backupId($backup['id'] ?? null);
        $release = releaseValue($backup['release'] ?? null);
        $time = $backup['created_at'] ?? null;
        if ($id !== null && $release !== null && is_string($time) && preg_match('/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\z/', $time)) {
            $backups[] = ['id' => $id, 'release' => $release, 'created_at' => $time];
        }
    }
    $status['backups'] = $backups;
    $status['available'] = $status['available'] && $backups !== [];
    $status['preserved'] = is_string($info['preserved'] ?? null) ? $info['preserved'] : null;
    return $status;
}

function upgradeNeedsRecovery(array $info): bool
{
    return $info['phase'] === 'recovery' || $info['state'] === 'interrupted';
}

function retentionInfo(): ?array
{
    [$code, $text] = helper(['retention_info']);
    $info = $code === 0 ? json_decode($text, true) : null;
    $days = $info['days'] ?? null;
    return is_int($days) && $days >= 0 && $days <= 3650 ? ['days' => $days] : null;
}

function autoUpgradeInfo(): ?array
{
    [$code, $text] = helper(['auto_upgrade_info']);
    $info = $code === 0 ? json_decode($text, true) : null;
    $enabled = $info['enabled'] ?? null;
    if (!is_bool($enabled)) {
        return null;
    }
    return ['enabled' => $enabled, 'last_attempt' => releaseValue($info['last_attempt'] ?? null)];
}

function prerequisites(): array
{
    $docker = null;
    foreach (['/usr/bin/docker', '/usr/local/bin/docker', '/usr/local/sbin/docker'] as $path) {
        if (is_executable($path)) {
            $docker = $path;
            break;
        }
    }
    $compose = false;
    if ($docker !== null) {
        [$code, $version] = command([$docker, 'compose', 'version', '--short'], 5);
        $compose = $code === 0 && version_compare(ltrim(trim($version), 'v'), '2.24.4', '>=');
    }
    $var = @parse_ini_file('/var/local/emhttp/var.ini', false, INI_SCANNER_RAW) ?: [];
    return [
        'compose' => $compose,
        'array_started' => ($var['mdState'] ?? '') === 'STARTED',
    ];
}

function requireReady(array $ready): void
{
    if (!$ready['compose']) {
        reply(['ok' => false, 'message' => 'Install Docker Compose before you start Fluxer.'], 409);
    }
    if (!$ready['array_started']) {
        reply(['ok' => false, 'message' => 'Start the Unraid array before you configure Fluxer.'], 409);
    }
}

function validDomain(string $value): bool
{
    if (strlen($value) > 253 || strpos($value, '.') === false) {
        return false;
    }
    foreach (explode('.', $value) as $label) {
        if (!preg_match('/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/D', $label)) {
            return false;
        }
    }
    return true;
}

function validNasAddress(string $value): bool
{
    if (!filter_var($value, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
        return false;
    }
    $octets = array_map('intval', explode('.', $value));
    return $octets[0] === 10
        || ($octets[0] === 172 && $octets[1] >= 16 && $octets[1] <= 31)
        || ($octets[0] === 192 && $octets[1] === 168)
        || ($octets[0] === 100 && $octets[1] >= 64 && $octets[1] <= 127);
}

function savedValue(string $name): ?string
{
    if (!in_array($name, ['FLUXER_DOMAIN', 'FLUXER_SETUP_TOKEN'], true)) {
        return null;
    }
    $file = @fopen(FLUXER_PROJECT . '/.env', 'r');
    if ($file === false) {
        return null;
    }
    $value = null;
    while (($line = fgets($file)) !== false) {
        if (str_starts_with($line, $name . '=')) {
            $candidate = trim(substr($line, strlen($name) + 1));
            if (strlen($candidate) >= 2 && (($candidate[0] === "'" && substr($candidate, -1) === "'") || ($candidate[0] === '"' && substr($candidate, -1) === '"'))) {
                $candidate = substr($candidate, 1, -1);
            }
            $value = $candidate;
        }
    }
    fclose($file);
    return $value;
}

function token(string $name, bool $required): string
{
    $value = field($name);
    if ($value === '' && !$required) {
        return '';
    }
    if (strlen($value) < 20 || strlen($value) > 8192 || !preg_match('/^[A-Za-z0-9_+\/=.-]+$/D', $value)) {
        reply(['ok' => false, 'message' => $value === '' ? 'Enter both Cloudflare tokens before you save setup.' : 'The token contains invalid characters.'], 400);
    }
    return $value;
}

function saveTokens(string $dns, string $tunnel): void
{
    $directory = FLUXER_PROJECT . '/secrets';
    if (!is_dir($directory) || is_link($directory)) {
        reply(['ok' => false, 'message' => 'The token folder is not available.'], 500);
    }
    umask(0077);
    $lock = @fopen('/var/lock/fluxer-unraid.lock', 'c');
    if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
        if (is_resource($lock)) {
            fclose($lock);
        }
        reply(['ok' => false, 'message' => 'Operation in progress. Refresh the status before you save tokens.'], 409);
    }
    if (file_exists(FLUXER_UPGRADE_PENDING) || is_link(FLUXER_UPGRADE_PENDING)) {
        reply(['ok' => false, 'message' => 'Follow the recovery steps before you save tokens.'], 409);
    }
    $changed = false;
    foreach (['cloudflare-dns-token' => $dns, 'cloudflare-tunnel-token' => $tunnel] as $name => $value) {
        if ($value === '') {
            continue;
        }
        $temporary = tempnam($directory, '.token-');
        if ($temporary === false) {
            reply(['ok' => false, 'message' => 'The token file could not be saved.'], 500);
        }
        $saved = file_put_contents($temporary, $value) === strlen($value) && chmod($temporary, 0600) && rename($temporary, $directory . '/' . $name);
        if (!$saved) {
            @unlink($temporary);
            reply(['ok' => false, 'message' => 'The token file could not be saved.'], 500);
        }
        $changed = true;
    }
    if ($changed) {
        $marker = FLUXER_PROJECT . '/.cloudflare-tokens-changed';
        if (is_link($marker) || file_put_contents($marker, "1\n", LOCK_EX) === false || !chmod($marker, 0600)) {
            reply(['ok' => false, 'message' => 'The token change could not be saved.'], 500);
        }
    }
    flock($lock, LOCK_UN);
    fclose($lock);
}

$action = field('action');
if (!in_array($action, ['configure', 'save_tokens', 'start', 'stop', 'status', 'setup_token', 'upgrade', 'restore', 'retention_set', 'auto_upgrade_set'], true)) {
    reply(['ok' => false, 'message' => 'The requested action is not available.'], 400);
}
if ($action === 'status') {
    $ready = prerequisites();
    [$code, $text] = helper(['status']);
    $upgrade = operationInfo('upgrade');
    $restore = operationInfo('restore');
    $domain = savedValue('FLUXER_DOMAIN');
    reply([
        'ok' => true,
        'configured' => is_file(FLUXER_PROJECT . '/.env'),
        'prerequisites' => $ready,
        'exit_code' => $code,
        'status' => $text,
        'pending' => strpos($text, 'Operation in progress.') !== false
            || $upgrade['state'] === 'running' || $restore['state'] === 'running',
        'upgrade' => $upgrade,
        'restore' => $restore,
        'retention' => retentionInfo(),
        'auto_upgrade' => autoUpgradeInfo(),
        'url' => $domain !== null && validDomain($domain) ? 'https://' . $domain : null,
    ]);
}

if ($action === 'setup_token') {
    $value = savedValue('FLUXER_SETUP_TOKEN');
    if ($value === null || !preg_match('/^[A-Za-z0-9_-]{32,256}$/D', $value)) {
        reply(['ok' => false, 'message' => 'The setup token is not available.'], 409);
    }
    reply(['ok' => true, 'token' => $value]);
}

$configured = is_file(FLUXER_PROJECT . '/.env');
if ($action === 'configure') {
    if ($configured) {
        reply(['ok' => false, 'message' => 'Setup already exists. Use Save tokens to change the Cloudflare tokens.'], 409);
    }
    $domain = field('domain');
    $email = field('email');
    $nas = field('nas_ip');
    if (!validDomain($domain)) {
        reply(['ok' => false, 'message' => 'Enter a lowercase domain without a scheme, port, or path.'], 400);
    }
    if (!filter_var($email, FILTER_VALIDATE_EMAIL) || !preg_match('/^[a-zA-Z0-9@._+%\-]+$/D', $email)) {
        reply(['ok' => false, 'message' => 'Enter an email address for certificate notices.'], 400);
    }
    if (!validNasAddress($nas)) {
        reply(['ok' => false, 'message' => 'Enter the private IPv4 address of the NAS on your local network.'], 400);
    }
    $dns = token('dns_token', true);
    $tunnel = token('tunnel_token', true);
    requireReady(prerequisites());
    [$code, $text] = helper(['prepare', $domain, $email, $nas]);
    if ($code !== 0) {
        reply(['ok' => false, 'message' => 'The setup command failed.', 'detail' => $text, 'exit_code' => $code], 500);
    }
    saveTokens($dns, $tunnel);
    reply(['ok' => true, 'message' => 'Setup saved. Configure the tunnel hostname, then select Start Fluxer.']);
}

if ($action === 'retention_set') {
    $days = field('days');
    if (!preg_match('/\A(?:0|[1-9][0-9]{0,3})\z/', $days) || (int) $days > 3650) {
        reply(['ok' => false, 'message' => 'Enter a retention period from 0 to 3650 days.'], 400);
    }
    if (!prerequisites()['array_started']) {
        reply(['ok' => false, 'message' => 'Start the Unraid array before you save retention settings.'], 409);
    }
    [$code, $text] = helper(['retention_set', $days]);
    if ($code !== 0) {
        reply(['ok' => false, 'message' => $text !== '' ? $text : 'The controller could not save retention settings.'], 409);
    }
    reply(['ok' => true, 'message' => 'Backup retention saved. The daily job applies this setting.']);
}

if ($action === 'auto_upgrade_set') {
    $enabled = $_POST['enabled'] ?? null;
    if (!in_array($enabled, ['on', 'off'], true)) {
        reply(['ok' => false, 'message' => 'Select on or off for automatic upgrades.'], 400);
    }
    if (!prerequisites()['array_started']) {
        reply(['ok' => false, 'message' => 'Start the Unraid array before you save automatic upgrades.'], 409);
    }
    [$code, $text] = helper(['auto_upgrade_set', $enabled]);
    if ($code !== 0) {
        reply(['ok' => false, 'message' => $text !== '' ? $text : 'The controller could not save automatic upgrades.'], 409);
    }
    reply(['ok' => true, 'message' => 'Automatic upgrade setting saved.']);
}

if (!$configured && $action !== 'restore') {
    reply(['ok' => false, 'message' => 'Save setup before you start Fluxer.'], 409);
}

if ($action === 'save_tokens') {
    saveTokens(token('dns_token', false), token('tunnel_token', false));
    reply(['ok' => true, 'message' => 'Tokens saved. Select Start Fluxer to apply them.']);
}

if ($action === 'start') {
    requireReady(prerequisites());
    [$code, $text] = helper(['check']);
    if ($code !== 0) {
        reply(['ok' => false, 'message' => $text !== '' ? $text : 'Fluxer is not ready to start.'], 409);
    }
}
$arguments = [];
$requestId = null;
if ($action === 'upgrade') {
    requireReady(prerequisites());
    $target = releaseValue(field('target'));
    $upgrade = operationInfo('upgrade');
    if ($target === null || $target !== $upgrade['target']) {
        reply(['ok' => false, 'message' => 'The bundled release changed. Refresh the status before you try again.'], 409);
    }
    if (!$upgrade['available'] || $upgrade['state'] === 'running' || upgradeNeedsRecovery($upgrade)) {
        $message = $upgrade['message'] ?: 'The upgrade status is not available.';
        reply(['ok' => false, 'message' => $message], 409);
    }
    $requestId = bin2hex(random_bytes(16));
    $arguments = [$target, $requestId];
}
if ($action === 'restore') {
    $id = backupId(field('backup_id'));
    if ($id === null) {
        reply(['ok' => false, 'message' => 'Select a valid backup.'], 400);
    }
    requireReady(prerequisites());
    $restore = operationInfo('restore');
    if (!in_array($id, array_column($restore['backups'], 'id'), true)) {
        reply(['ok' => false, 'message' => 'The selected backup is unavailable. Refresh the status and select a backup.'], 409);
    }
    if (!$restore['available'] || $restore['state'] === 'running') {
        $message = $restore['message'] ?: 'The controller cannot read the restore status.';
        reply(['ok' => false, 'message' => $message], 409);
    }
    $requestId = bin2hex(random_bytes(16));
    $arguments = [$id, $requestId];
}
if (in_array($action, ['start', 'stop', 'upgrade', 'restore'], true)) {
    $helper = FLUXER_PLUGIN . '/scripts/fluxerctl';
    if (!is_executable($helper) || is_link(FLUXER_LOG)) {
        reply(['ok' => false, 'message' => 'The controller could not start.'], 500);
    }
    umask(0077);
    $log = @fopen(FLUXER_LOG, 'a');
    if ($log === false) {
        reply(['ok' => false, 'message' => 'The controller could not start.'], 500);
    }
    fclose($log);
    chmod(FLUXER_LOG, 0600);
    $background = 'nohup ' . implode(' ', array_map('escapeshellarg', [$helper, $action, ...$arguments]))
        . ' </dev/null >>' . escapeshellarg(FLUXER_LOG) . ' 2>&1 &';
    exec($background, $unused, $code);
    if ($code !== 0) {
        reply(['ok' => false, 'message' => 'The controller could not start.'], 500);
    }
    $message = match ($action) {
        'start' => 'Start requested. The first download can take several minutes.',
        'stop' => 'Stop requested.',
        'upgrade' => 'Upgrade requested. The status refreshes while the upgrade runs.',
        'restore' => 'Restore requested. The status refreshes while the restore runs.',
    };
    reply(['ok' => true, 'pending' => true, 'message' => $message, 'request_id' => $requestId]);
}
