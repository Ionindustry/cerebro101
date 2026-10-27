// Command ingestor: Conectores y planificador de la ingesta (PLACSP, TED, Cataluña). Llegan en la fase 1.
package main

import (
	"net/http"
	"os"

	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
)

func main() {
	os.Exit(service.Main("ingestor", func(_ *http.ServeMux) {}))
}
