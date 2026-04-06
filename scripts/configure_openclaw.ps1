param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$OpenClawDir = (Join-Path $HOME ".openclaw"),
    [switch]$EnablePlaywright,
    [switch]$EnableAcpx,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Ensure-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $DefaultValue
    )

    $propertyNames = @($Object.PSObject.Properties.Name)
    if ($propertyNames -notcontains $Name -or $null -eq $Object.$Name) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $DefaultValue -Force
    }

    return $Object.PSObject.Properties[$Name].Value
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )

    $propertyNames = @($Object.PSObject.Properties.Name)
    if ($propertyNames -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value -Force
    }
}

function Remove-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) {
        $Object.PSObject.Properties.Remove($Name)
    }
}

function Ensure-ArrayValue {
    param(
        $ArrayRef,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $items = @($ArrayRef) | Where-Object { $null -ne $_ -and "$_".Trim() -ne "" }
    if ($items -notcontains $Value) {
        $items += $Value
    }
    return ,$items
}

function Set-ServerEntry {
    param(
        [Parameter(Mandatory = $true)]$Container,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][hashtable]$Value
    )

    $propertyNames = @($Container.PSObject.Properties.Name)
    if ($propertyNames -contains $Name) {
        $Container.$Name = [pscustomobject]$Value
    } else {
        $Container | Add-Member -MemberType NoteProperty -Name $Name -Value ([pscustomobject]$Value)
    }
}

$openClawConfigPath = Join-Path $OpenClawDir "openclaw.json"
$mcporterConfigPath = Join-Path $OpenClawDir "workspace\config\mcporter.json"
$mcporterConfigDir = Split-Path -Parent $mcporterConfigPath
$repoSkillDir = Join-Path $RepoRoot "openclaw\skills"
$workspaceDir = Join-Path $OpenClawDir "workspace"
$githubEnvFile = Join-Path $HOME ".secrets\github-mcp.env"

if (-not (Test-Path $openClawConfigPath)) {
    throw "OpenClaw config not found at $openClawConfigPath"
}

if (-not (Test-Path $repoSkillDir)) {
    throw "Repo skill directory not found at $repoSkillDir"
}

if (-not (Test-Path $mcporterConfigDir)) {
    New-Item -ItemType Directory -Path $mcporterConfigDir -Force | Out-Null
}

$config = Get-Content $openClawConfigPath -Raw | ConvertFrom-Json
$agents = Ensure-ObjectProperty -Object $config -Name "agents" -DefaultValue ([pscustomobject]@{})
$defaults = Ensure-ObjectProperty -Object $agents -Name "defaults" -DefaultValue ([pscustomobject]@{})
$skills = Ensure-ObjectProperty -Object $config -Name "skills" -DefaultValue ([pscustomobject]@{})
$skillLoad = Ensure-ObjectProperty -Object $skills -Name "load" -DefaultValue ([pscustomobject]@{})
$skillEntries = Ensure-ObjectProperty -Object $skills -Name "entries" -DefaultValue ([pscustomobject]@{})
$plugins = Ensure-ObjectProperty -Object $config -Name "plugins" -DefaultValue ([pscustomobject]@{})
$pluginEntries = Ensure-ObjectProperty -Object $plugins -Name "entries" -DefaultValue ([pscustomobject]@{})
$mcp = Ensure-ObjectProperty -Object $config -Name "mcp" -DefaultValue ([pscustomobject]@{})
$mcpServers = Ensure-ObjectProperty -Object $mcp -Name "servers" -DefaultValue ([pscustomobject]@{})

if (-not $defaults.workspace) {
    Set-ObjectProperty -Object $defaults -Name "workspace" -Value $workspaceDir
}
Set-ObjectProperty -Object $defaults -Name "repoRoot" -Value $RepoRoot
Remove-ObjectProperty -Object $defaults -Name "skills"
Set-ObjectProperty -Object $skillLoad -Name "extraDirs" -Value ([object[]](Ensure-ArrayValue -ArrayRef $skillLoad.extraDirs -Value $repoSkillDir))

$jarvisSkill = Ensure-ObjectProperty -Object $skillEntries -Name "jarvismax-autonomy" -DefaultValue ([pscustomobject]@{})
Set-ObjectProperty -Object $jarvisSkill -Name "enabled" -Value $true

$ghIssuesSkill = Ensure-ObjectProperty -Object $skillEntries -Name "gh-issues" -DefaultValue ([pscustomobject]@{})
Set-ObjectProperty -Object $ghIssuesSkill -Name "enabled" -Value $true
Set-ObjectProperty -Object $ghIssuesSkill -Name "apiKey" -Value ([pscustomobject]@{
    source = "env"
    provider = "default"
    id = "GH_TOKEN"
})

foreach ($pluginName in @("duckduckgo", "browser", "diffs")) {
    $plugin = Ensure-ObjectProperty -Object $pluginEntries -Name $pluginName -DefaultValue ([pscustomobject]@{})
    Set-ObjectProperty -Object $plugin -Name "enabled" -Value $true
}

if ($EnableAcpx) {
    $acpx = Ensure-ObjectProperty -Object $pluginEntries -Name "acpx" -DefaultValue ([pscustomobject]@{})
    Set-ObjectProperty -Object $acpx -Name "enabled" -Value $true
}

Set-ServerEntry -Container $mcpServers -Name "jarvis-filesystem" -Value @{
    command = "npx"
    args = @("-y", "@modelcontextprotocol/server-filesystem", $RepoRoot)
    cwd = $RepoRoot
}

Set-ServerEntry -Container $mcpServers -Name "jarvis-git" -Value @{
    command = "uvx"
    args = @("mcp-server-git", "--repository", $RepoRoot)
    cwd = $RepoRoot
}

Set-ServerEntry -Container $mcpServers -Name "jarvis-memory" -Value @{
    command = "npx"
    args = @("-y", "@modelcontextprotocol/server-memory")
    cwd = $workspaceDir
}

if (Test-Path $githubEnvFile) {
    Set-ServerEntry -Container $mcpServers -Name "jarvis-github" -Value @{
        command = "docker"
        args = @("run", "-i", "--rm", "--env-file", $githubEnvFile, "ghcr.io/github/github-mcp-server:latest")
    }
}

if ($EnablePlaywright) {
    Set-ServerEntry -Container $mcpServers -Name "jarvis-playwright" -Value @{
        command = "npx"
        args = @("-y", "@modelcontextprotocol/server-playwright")
        cwd = $RepoRoot
    }
}

if (Test-Path $mcporterConfigPath) {
    $mcporter = Get-Content $mcporterConfigPath -Raw | ConvertFrom-Json
} else {
    $mcporter = [pscustomobject]@{}
}

$mcporterServers = Ensure-ObjectProperty -Object $mcporter -Name "mcpServers" -DefaultValue ([pscustomobject]@{})

if (Test-Path $githubEnvFile) {
    Set-ServerEntry -Container $mcporterServers -Name "github" -Value @{
        command = "docker"
        args = @("run", "-i", "--rm", "--env-file", $githubEnvFile, "ghcr.io/github/github-mcp-server:latest")
    }
}

Set-ServerEntry -Container $mcporterServers -Name "jarvis-filesystem" -Value @{
    command = "npx"
    args = @("-y", "@modelcontextprotocol/server-filesystem", $RepoRoot)
}

Set-ServerEntry -Container $mcporterServers -Name "jarvis-git" -Value @{
    command = "uvx"
    args = @("mcp-server-git", "--repository", $RepoRoot)
}

Set-ServerEntry -Container $mcporterServers -Name "jarvis-memory" -Value @{
    command = "npx"
    args = @("-y", "@modelcontextprotocol/server-memory")
}

if ($EnablePlaywright) {
    Set-ServerEntry -Container $mcporterServers -Name "jarvis-playwright" -Value @{
        command = "npx"
        args = @("-y", "@modelcontextprotocol/server-playwright")
    }
}

if ($DryRun) {
    [pscustomobject]@{
        openclawConfigPath = $openClawConfigPath
        mcporterConfigPath = $mcporterConfigPath
        repoRoot = $RepoRoot
        repoSkillDir = $repoSkillDir
        openclawPlugins = @($pluginEntries.PSObject.Properties.Name | Sort-Object)
        openclawMcpServers = @($mcpServers.PSObject.Properties.Name | Sort-Object)
        mcporterServers = @($mcporterServers.PSObject.Properties.Name | Sort-Object)
        githubEnvFilePresent = (Test-Path $githubEnvFile)
    } | ConvertTo-Json -Depth 10
    exit 0
}

$backupStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$openClawConfigPath.bak.$backupStamp"
Copy-Item -LiteralPath $openClawConfigPath -Destination $backupPath -Force

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($openClawConfigPath, ($config | ConvertTo-Json -Depth 100), $utf8NoBom)
[System.IO.File]::WriteAllText($mcporterConfigPath, ($mcporter | ConvertTo-Json -Depth 100), $utf8NoBom)

[pscustomobject]@{
    openclawConfigPath = $openClawConfigPath
    openclawBackupPath = $backupPath
    mcporterConfigPath = $mcporterConfigPath
    repoRoot = $RepoRoot
    repoSkillDir = $repoSkillDir
    githubEnvFilePresent = (Test-Path $githubEnvFile)
} | ConvertTo-Json -Depth 10
