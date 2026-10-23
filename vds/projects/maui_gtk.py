"""Dateien für eine MAUI-App mit GTK4-Backend (Microsoft.Maui.Platforms.Linux.Gtk4, dotnet/maui-labs, MIT, experimentell).
Der Aufbau folgt der mitgelieferten Vorlage des Pakets. Kein Workload nötig – nur NuGet-Pakete."""

GTK_VERSION = "0.1.0-preview.13.26512.5"

MAIN_PAGE = """using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;

namespace __ID__;

public class MainPage : ContentPage
{
    private int _count;

    public MainPage()
    {
        var label = new Label { Text = "Hallo, __NAME__!", FontSize = 32, HorizontalOptions = LayoutOptions.Center };
        var countLabel = new Label { Text = "Noch nicht geklickt", FontSize = 18, HorizontalOptions = LayoutOptions.Center };
        var button = new Button { Text = "Klick mich", HorizontalOptions = LayoutOptions.Center };

        button.Clicked += (s, e) =>
        {
            _count++;
            countLabel.Text = $"Geklickt: {_count}";
        };

        Content = new VerticalStackLayout
        {
            Spacing = 25,
            Padding = 30,
            VerticalOptions = LayoutOptions.Center,
            Children = { label, button, countLabel },
        };
    }
}
"""

PROGRAM = """using System.Runtime.Versioning;
using Microsoft.Maui.Platforms.Linux.Gtk4.Platform;
using Microsoft.Maui.Hosting;

[assembly: SupportedOSPlatform("linux")]

namespace __ID__;

public class Program : GtkMauiApplication
{
    protected override MauiApp CreateMauiApp() => MauiProgram.CreateMauiApp();

    public static void Main(string[] args)
    {
        var app = new Program();
        app.Run(args);
    }
}
"""

APP = """using Microsoft.Maui.Controls;

namespace __ID__;

public class App : Application
{
    protected override Window CreateWindow(IActivationState? activationState)
    {
        return new Window(new MainPage());
    }
}
"""


def maui_gtk_files(opts: dict) -> dict:
    ess = opts.get("essentials", True)
    pkgs = f'    <PackageReference Include="Microsoft.Maui.Platforms.Linux.Gtk4" Version="{GTK_VERSION}" />\n'
    if ess:
        pkgs += f'    <PackageReference Include="Microsoft.Maui.Platforms.Linux.Gtk4.Essentials" Version="{GTK_VERSION}" />\n'
    csproj = (
        '<Project Sdk="Microsoft.NET.Sdk">\n\n  <PropertyGroup>\n    <TargetFramework>net10.0</TargetFramework>\n    <OutputType>Exe</OutputType>\n'
        '    <RootNamespace>__ID__</RootNamespace>\n    <ImplicitUsings>enable</ImplicitUsings>\n    <Nullable>enable</Nullable>\n'
        '    <ApplicationId>com.companyname.__IDLOWER__</ApplicationId>\n    <ApplicationTitle>__NAME__</ApplicationTitle>\n  </PropertyGroup>\n\n'
        f'  <ItemGroup>\n{pkgs}  </ItemGroup>\n\n</Project>\n')
    usings = "using Microsoft.Maui.Platforms.Linux.Gtk4.Hosting;\nusing Microsoft.Maui.Hosting;\n"
    builder = "        var builder = MauiApp\n            .CreateBuilder()\n            .UseMauiAppLinuxGtk4<App>();\n\n"
    if ess:
        usings += "using Microsoft.Maui.Platforms.Linux.Gtk4.Essentials.Hosting;\n"
        builder += "        builder.AddLinuxGtk4Essentials();\n\n"
    maui_program = (usings + "\nnamespace __ID__;\n\npublic static class MauiProgram\n{\n    public static MauiApp CreateMauiApp()\n    {\n"
                    + builder + "        return builder.Build();\n    }\n}\n")
    return {"__NAME__.csproj": csproj, "Program.cs": PROGRAM, "MauiProgram.cs": maui_program, "App.cs": APP, "MainPage.cs": MAIN_PAGE}
