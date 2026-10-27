// Package version expone la versión del binario. Version se fija al compilar con
// -ldflags "-X github.com/ionindustry/cerebro101/licitaciones/internal/version.Version=<sha>".
package version

import "runtime/debug"

// Version es el identificador de compilación (el SHA del commit en la imagen); "dev" en local.
var Version = "dev"

// String devuelve la versión; si no se fijó al compilar, usa la revisión que Go incrusta en el binario.
func String() string {
	if Version != "dev" {
		return Version
	}
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, s := range info.Settings {
			if s.Key == "vcs.revision" && s.Value != "" {
				return s.Value
			}
		}
	}
	return Version
}
