#
# Module manifest for module 'TinyShell'
#

@{

# Script module or binary module file associated with this manifest.
RootModule = 'TinyShell.psm1'

# Version number of this module.
ModuleVersion = '1.0.0'

# Supported PSEditions
CompatiblePSEditions = @('Core')

# ID used to uniquely identify this module
GUID = '8f3b2d1c-9e7a-4a25-b83c-1d5e7f9a2b4c'

# Author of this module
Author = 'TinyShell Team'

# Company or vendor of this module
CompanyName = 'Community'

# Copyright statement for this module
Copyright = '(c) 2026 TinyShell Intent Project. All rights reserved.'

# Description of the functionality provided by this module
Description = 'Offline lightweight semantic command intent suggestion plugin for Windows PowerShell 7.'

# Minimum version of the PowerShell engine required by this module
PowerShellVersion = '7.4'

# Assemblies that must be loaded prior to importing this module
NestedModules = @('TinyShell.PowerShell.dll')

# Cmdlets to export from this module
CmdletsToExport = @('Get-TinyIntent', 'Initialize-TinyIntent')

# Functions to export from this module
FunctionsToExport = @('Register-TinyIntentKeyHandler', 'Unregister-TinyIntentKeyHandler', 'Invoke-TinyShellBufferSimulation')

# List of all files packaged with this module
FileList = @(
    'TinyShell.psd1',
    'TinyShell.psm1',
    'TinyShell.PowerShell.dll',
    'TinyShell.Core.dll'
)

# Private data to pass to the module specified in RootModule
PrivateData = @{
    PSData = @{
        Tags = @('shell', 'intent', 'autocomplete', 'offline', 'nlp', 'model2vec')
        ProjectUri = 'https://github.com/zhkai-ybwn/tiny-shell-intent'
    }
}

}
