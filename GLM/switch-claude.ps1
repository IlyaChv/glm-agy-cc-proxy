# switch-claude.ps1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$claudeDir = Join-Path $env:USERPROFILE ".claude"
$settingsFile = Join-Path $claudeDir "settings.json"
$backupFile = Join-Path $claudeDir "settings.anthropic.backup.json"
$keyFile = Join-Path $claudeDir "zai_api_key.txt"

if (-not (Test-Path $claudeDir)) {
    New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
}

# Windows PowerShell 5.1 пишет UTF8 с BOM, а BOM ломает разбор settings.json.
function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

# Ключи, которые добавляет режим GLM. Всё остальное в settings.json не трогается:
# permissions.allow (в том числе разрешения на agy-run и glm-run) и autoMode переживают переключение.
$glmEnv = [ordered]@{
    "ANTHROPIC_BASE_URL"                       = "https://api.z.ai/api/anthropic"
    "ANTHROPIC_AUTH_TOKEN"                     = ""
    "ANTHROPIC_DEFAULT_HAIKU_MODEL"            = "glm-5.3-flash[1m]"
    "ANTHROPIC_DEFAULT_SONNET_MODEL"           = "glm-5.3[1m]"
    "ANTHROPIC_DEFAULT_OPUS_MODEL"             = "glm-5.3[1m]"
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW"          = "1000000"
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" = 1
    "API_TIMEOUT_MS"                           = "3000000"
}

function Set-JsonProp {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

# Бросает исключение на битом JSON — вызывающий обязан поймать и не трогать файл.
function Read-Settings {
    if (-not (Test-Path $settingsFile)) { return $null }
    $raw = Get-Content $settingsFile -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) { return [PSCustomObject]@{} }
    return ($raw | ConvertFrom-Json)
}

function Save-Settings {
    param($Settings)
    $json = $Settings | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $settingsFile -Content $json
}

# Сначала claude из PATH; если его нет — бинарник внутри десктоп-приложения, в папке с номером
# версии, который меняется при обновлении. Берём самую свежую.
function Get-ClaudeExe {
    $onPath = Get-Command claude -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $root = Join-Path $env:APPDATA "Claude\claude-code"
    if (Test-Path $root) {
        $exe = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
               Sort-Object { try { [version]$_.Name } catch { [version]"0.0.0" } } -Descending |
               ForEach-Object { Join-Path $_.FullName "claude.exe" } |
               Where-Object { Test-Path $_ } |
               Select-Object -First 1
        if ($exe) { return $exe }
    }
    return $null
}

# Десктоп-приложение подхватывает env из settings.json на лету, а когда ключи из файла удаляют,
# со своего процесса их не снимает: открытые из него терминалы наследуют прежние значения.
function Show-RestartHint {
    if (Get-Process -Name claude -ErrorAction SilentlyContinue) {
        Write-Host "Claude сейчас запущен. Закройте его полностью, включая иконку в трее, и откройте заново:" -ForegroundColor Yellow
        Write-Host "до перезапуска он и открытые из него терминалы держат прежние переменные env." -ForegroundColor Yellow
    }
}

function Get-CurrentMode {
    if (-not (Test-Path $settingsFile)) {
        return "Anthropic (Официальный)"
    }
    $content = Get-Content $settingsFile -Raw -Encoding UTF8
    if ($content -match "api\.z\.ai") {
        return "Z.AI GLM"
    }
    return "Anthropic (Пользовательский)"
}

function Switch-To-GLM {
    $apiKey = ""
    if (Test-Path $keyFile) {
        $apiKey = (Get-Content $keyFile -Raw -Encoding UTF8).Trim()
    }

    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Host "Z.AI API ключ не найден." -ForegroundColor Yellow
        $apiKey = Read-Host "Введите ваш Z.AI API Key"
        $apiKey = $apiKey.Trim()
        if ([string]::IsNullOrWhiteSpace($apiKey)) {
            Write-Host "Ключ не может быть пустым!" -ForegroundColor Red
            return
        }
        Write-Utf8NoBom -Path $keyFile -Content $apiKey
        Write-Host "Ключ успешно сохранен в $keyFile" -ForegroundColor Green
    }

    # Если уже был settings.json не от Z.AI, сохраняем его резервную копию
    if ((Test-Path $settingsFile) -and ((Get-Content $settingsFile -Raw -Encoding UTF8) -notmatch "api\.z\.ai")) {
        Copy-Item $settingsFile $backupFile -Force
        Write-Host "Текущий settings.json сохранен в резервную копию." -ForegroundColor Gray
    }

    try {
        $settings = Read-Settings
    } catch {
        Write-Host "settings.json не разбирается как JSON — переключение отменено." -ForegroundColor Red
        Write-Host "Файл оставлен без изменений: $settingsFile" -ForegroundColor Red
        return
    }
    if ($null -eq $settings) { $settings = [PSCustomObject]@{} }

    if (($settings.PSObject.Properties.Name -contains "env") -and ($null -ne $settings.env)) {
        $envBlock = $settings.env
    } else {
        $envBlock = [PSCustomObject]@{}
    }

    foreach ($name in $glmEnv.Keys) {
        if ($name -eq "ANTHROPIC_AUTH_TOKEN") { $value = $apiKey } else { $value = $glmEnv[$name] }
        Set-JsonProp -Object $envBlock -Name $name -Value $value
    }
    Set-JsonProp -Object $settings -Name "env" -Value $envBlock

    Save-Settings -Settings $settings
    Write-Host "`n[OK] Claude Code успешно переключен на Z.AI GLM!" -ForegroundColor Green
    Write-Host "Остальные настройки (permissions, autoMode) сохранены." -ForegroundColor Gray
    Show-RestartHint
}

function Switch-To-Anthropic {
    if (-not (Test-Path $settingsFile)) {
        if (Test-Path $backupFile) {
            Copy-Item $backupFile $settingsFile -Force
            Write-Host "`n[OK] settings.json восстановлен из резервной копии." -ForegroundColor Green
            Show-RestartHint
        } else {
            Write-Host "`n[OK] Уже официальный Anthropic: settings.json отсутствует." -ForegroundColor Green
        }
        return
    }

    try {
        $settings = Read-Settings
    } catch {
        Write-Host "settings.json не разбирается как JSON — переключение отменено." -ForegroundColor Red
        Write-Host "Файл оставлен без изменений: $settingsFile" -ForegroundColor Red
        return
    }

    # Блок env восстанавливаем из копии целиком: если какие-то из этих ключей
    # стояли у вас до GLM, они вернутся со своими прежними значениями.
    $restoredFromBackup = $false
    if (Test-Path $backupFile) {
        try {
            $backup = (Get-Content $backupFile -Raw -Encoding UTF8) | ConvertFrom-Json
        } catch {
            $backup = $null
        }
        if ($null -ne $backup) {
            if ($backup.PSObject.Properties.Name -contains "env") {
                Set-JsonProp -Object $settings -Name "env" -Value $backup.env
            } else {
                $settings.PSObject.Properties.Remove("env")
            }
            $restoredFromBackup = $true
        }
    }

    if (-not $restoredFromBackup) {
        if ($settings.PSObject.Properties.Name -contains "env") {
            $envBlock = $settings.env
            if ($null -ne $envBlock) {
                foreach ($name in $glmEnv.Keys) { $envBlock.PSObject.Properties.Remove($name) }
                if (@($envBlock.PSObject.Properties).Count -eq 0) {
                    $settings.PSObject.Properties.Remove("env")
                }
            }
        }
    }

    Save-Settings -Settings $settings
    if ($restoredFromBackup) {
        Write-Host "`n[OK] Блок env восстановлен из резервной копии." -ForegroundColor Green
    } else {
        Write-Host "`n[OK] Ключи Z.AI удалены из settings.json." -ForegroundColor Green
    }
    Write-Host "Остальные настройки (permissions, autoMode) сохранены." -ForegroundColor Gray
    Show-RestartHint
}

function Change-ApiKey {
    $newKey = Read-Host "Введите новый Z.AI API Key"
    $newKey = $newKey.Trim()
    if (-not [string]::IsNullOrWhiteSpace($newKey)) {
        Write-Utf8NoBom -Path $keyFile -Content $newKey
        Write-Host "Ключ обновлен!" -ForegroundColor Green
        # Если сейчас активен GLM, перезаписываем settings.json
        if ((Get-CurrentMode) -eq "Z.AI GLM") {
            Switch-To-GLM
        }
    }
}

# Главный цикл меню
while ($true) {
    Clear-Host
    $currentMode = Get-CurrentMode
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "   Claude Code: Переключатель Моделей  " -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    if ($currentMode -eq "Z.AI GLM") {
        Write-Host "Текущий режим: " -NoNewline
        Write-Host "[$currentMode]" -ForegroundColor Green
    } else {
        Write-Host "Текущий режим: " -NoNewline
        Write-Host "[$currentMode]" -ForegroundColor Magenta
    }
    Write-Host "Действует на: терминальный claude (новый запуск)." -ForegroundColor DarkGray
    Write-Host "Вкладка Code в десктоп-приложении не переключается — см. README.md" -ForegroundColor DarkGray
    Write-Host "После смены режима перезапустите десктоп-приложение целиком, включая трей." -ForegroundColor DarkGray
    Write-Host "----------------------------------------"
    Write-Host "1. Переключить на Z.AI GLM"
    Write-Host "2. Переключить на Anthropic (Оригинальный)"
    Write-Host "3. Запустить Claude Code прямо сейчас"
    Write-Host "4. Сменить / ввести Z.AI API ключ"
    Write-Host "0. Выход"
    Write-Host "----------------------------------------"

    $choice = Read-Host "Выберите действие (0-4)"

    switch ($choice) {
        "1" {
            Switch-To-GLM
            Pause
        }
        "2" {
            Switch-To-Anthropic
            Pause
        }
        "3" {
            $exe = Get-ClaudeExe
            if ($null -eq $exe) {
                Write-Host "`nclaude не найден: ни в PATH, ни внутри десктоп-приложения." -ForegroundColor Red
                Write-Host "Установите CLI отдельно (с --allow-scripts, см. README.md), либо запускайте claude из своего терминала." -ForegroundColor Red
            } else {
                if ((Get-CurrentMode) -ne "Z.AI GLM") {
                    # Окно могло унаследовать ключи Z.AI от десктоп-приложения — в claude их не передаём.
                    foreach ($name in $glmEnv.Keys) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
                }
                Write-Host "`nЗапуск Claude Code: $exe" -ForegroundColor Cyan
                & $exe
            }
            Pause
        }
        "4" {
            Change-ApiKey
            Pause
        }
        "0" {
            exit
        }
        default {
            Write-Host "Неверный ввод, повторите попытку." -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
