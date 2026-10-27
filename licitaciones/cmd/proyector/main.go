// Command proyector: Proyectores de grafo y de búsqueda, reconstrucción y cola de errores. Llegan en las fases 1 y 3.
package main

import (
	"net/http"
	"os"

	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
)

func main() {
	os.Exit(service.Main("proyector", func(_ *http.ServeMux) {}))
}
