// Command api: API REST del motor (contrato en api/openapi.yaml). Los endpoints llegan en la fase 3.
package main

import (
	"net/http"
	"os"

	"github.com/ionindustry/cerebro101/licitaciones/internal/service"
)

func main() {
	os.Exit(service.Main("api", func(_ *http.ServeMux) {}))
}
