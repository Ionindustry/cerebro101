package main

// Catálogos fijos del banco de pruebas: CPV (lista reducida con jerarquía de prefijos), NUTS de España y fuentes.
// Los códigos CPV y NUTS son reales; los nombres son aproximados y solo sirven para que los datos se lean bien.
// No es un catálogo para producción: el motor cargará el CPV 2008 completo y la tabla NUTS oficial.

import (
	"sort"
	"strings"
)

type cpvEntry struct {
	Code string
	Name string
}

// cpvList: códigos CPV 2008 reales de las divisiones más frecuentes en la contratación pública española,
// más los once CPV de interés de 101.cat (§12.1 del proyecto).
var cpvList = []cpvEntry{
	{"03000000", "Productos de la agricultura, ganadería, pesca, silvicultura"},
	{"03400000", "Productos de la silvicultura y de la explotación forestal"},
	{"09000000", "Derivados del petróleo, combustibles, electricidad y otras fuentes de energía"},
	{"09100000", "Combustibles"},
	{"09130000", "Petróleo y destilados"},
	{"09134200", "Combustible diésel"},
	{"09300000", "Electricidad, calefacción, energía solar y nuclear"},
	{"09310000", "Electricidad"},
	{"09330000", "Energía solar"},
	{"09331000", "Paneles solares"},
	{"09332000", "Instalaciones solares"},
	{"15000000", "Alimentos, bebidas, tabaco y productos afines"},
	{"15800000", "Productos alimenticios diversos"},
	{"15894000", "Productos alimenticios elaborados"},
	{"18000000", "Prendas de vestir, calzado, artículos de viaje y accesorios"},
	{"18100000", "Ropa de trabajo, ropa de trabajo especial y accesorios"},
	{"18110000", "Ropa de trabajo"},
	{"22000000", "Impresos y productos relacionados"},
	{"22100000", "Libros impresos, folletos y prospectos"},
	{"30000000", "Máquinas, equipo y artículos de oficina y de informática"},
	{"30100000", "Máquinas, equipo y artículos de oficina"},
	{"30190000", "Equipo y artículos de oficina diversos"},
	{"30192000", "Artículos de oficina"},
	{"30200000", "Equipo y material informático"},
	{"30210000", "Máquinas procesadoras de datos (hardware)"},
	{"30213000", "Ordenadores personales"},
	{"30213100", "Ordenadores portátiles"},
	{"30230000", "Equipo relacionado con la informática"},
	{"30232000", "Equipo periférico"},
	{"31000000", "Máquinas, aparatos, equipo y productos consumibles eléctricos; iluminación"},
	{"31500000", "Aparatos de iluminación y lámparas eléctricas"},
	{"31520000", "Lámparas y accesorios de iluminación"},
	{"31527200", "Alumbrado exterior"},
	{"31600000", "Equipo y aparatos eléctricos"},
	{"31625000", "Alarmas antirrobo y contra incendios"},
	{"31625100", "Sistemas de detección de incendios"},
	{"31625200", "Sistemas de alarma contra incendios"},
	{"31625300", "Sistemas de alarma antirrobo"},
	{"32000000", "Equipos de radio, televisión, comunicaciones y telecomunicaciones"},
	{"32200000", "Aparatos transmisores de radiotelefonía, radiotelegrafía, radiodifusión y televisión"},
	{"32230000", "Aparatos de transmisión de radio con receptor"},
	{"32300000", "Receptores de televisión y de radio, y aparatos de grabación o reproducción"},
	{"32320000", "Equipo de televisión y audiovisual"},
	{"32323500", "Sistema de videovigilancia"},
	{"32400000", "Redes"},
	{"32412000", "Red de comunicaciones"},
	{"32412100", "Red de telecomunicaciones"},
	{"32420000", "Equipo de red"},
	{"32500000", "Equipo y material de telecomunicaciones"},
	{"32550000", "Equipo telefónico"},
	{"33000000", "Equipamiento y artículos médicos, farmacéuticos y de higiene personal"},
	{"33100000", "Equipamiento médico"},
	{"33140000", "Material médico fungible"},
	{"33141000", "Productos médicos fungibles no químicos y fungibles hematológicos"},
	{"33600000", "Productos farmacéuticos"},
	{"33690000", "Medicamentos diversos"},
	{"34000000", "Equipos de transporte y productos auxiliares"},
	{"34100000", "Vehículos de motor"},
	{"34110000", "Turismos"},
	{"34144000", "Vehículos de motor para usos específicos"},
	{"34144210", "Vehículos de extinción de incendios"},
	{"34928500", "Equipo de alumbrado público"},
	{"35000000", "Equipo de seguridad, extinción de incendios, policía y defensa"},
	{"35100000", "Equipo de emergencia y seguridad"},
	{"35110000", "Equipo de extinción de incendios, rescate y seguridad"},
	{"35111000", "Equipo de extinción de incendios"},
	{"35111300", "Extintores"},
	{"35120000", "Sistemas y dispositivos de vigilancia y seguridad"},
	{"35121000", "Equipo de seguridad"},
	{"35125000", "Sistemas de vigilancia"},
	{"35125100", "Sensores"},
	{"35125300", "Cámaras de seguridad"},
	{"39000000", "Mobiliario, accesorios, aparatos electrodomésticos y productos de limpieza"},
	{"39100000", "Mobiliario"},
	{"39130000", "Mobiliario de oficina"},
	{"39160000", "Mobiliario escolar"},
	{"42000000", "Maquinaria industrial"},
	{"42500000", "Equipo de refrigeración y ventilación"},
	{"42510000", "Intercambiadores de calor, equipo de aire acondicionado y de refrigeración"},
	{"44000000", "Estructuras y materiales de construcción; productos auxiliares"},
	{"44100000", "Materiales de construcción y elementos afines"},
	{"44110000", "Materiales de construcción"},
	{"45000000", "Trabajos de construcción"},
	{"45200000", "Trabajos generales de construcción de inmuebles y obras de ingeniería civil"},
	{"45210000", "Trabajos de construcción de inmuebles"},
	{"45230000", "Trabajos de construcción de tuberías, líneas de comunicaciones y de conducción eléctrica, carreteras"},
	{"45233000", "Trabajos de construcción, de cimentación y de superficie de carreteras"},
	{"45233141", "Trabajos de mantenimiento de carreteras"},
	{"45233142", "Trabajos de reparación de carreteras"},
	{"45300000", "Trabajos de instalación en edificios"},
	{"45310000", "Trabajos de instalación eléctrica"},
	{"45311000", "Trabajos de cableado e instalación eléctrica"},
	{"45312000", "Trabajos de instalación de sistemas de alarma y antenas"},
	{"45312100", "Trabajos de instalación de sistemas de alarma contra incendios"},
	{"45312200", "Trabajos de instalación de sistemas de alarma antirrobo"},
	{"45314000", "Instalación de equipos de telecomunicaciones"},
	{"45315000", "Trabajos de instalación eléctrica de calefacción y otros equipos eléctricos de edificios"},
	{"45316000", "Trabajos de instalación de sistemas de iluminación y señalización"},
	{"45317000", "Otros trabajos de instalación eléctrica"},
	{"45320000", "Trabajos de aislamiento"},
	{"45330000", "Trabajos de fontanería"},
	{"45331000", "Trabajos de instalación de calefacción, ventilación y aire acondicionado"},
	{"45340000", "Trabajos de instalación de vallas, pasamanos y dispositivos de seguridad"},
	{"45343000", "Trabajos de instalación de dispositivos de prevención de incendios"},
	{"45343100", "Trabajos de ignifugación"},
	{"45400000", "Trabajos de acabado de edificios"},
	{"45421000", "Trabajos de carpintería"},
	{"45442100", "Trabajos de pintura"},
	{"45450000", "Otros trabajos de acabado de edificios"},
	{"45453000", "Trabajos de reacondicionamiento y restauración"},
	{"45454000", "Trabajos de reestructuración"},
	{"48000000", "Paquetes de software y sistemas de información"},
	{"48100000", "Paquetes de software para industrias específicas"},
	{"48200000", "Paquetes de software de redes, Internet e intranet"},
	{"48600000", "Paquetes de software de bases de datos y de funcionamiento"},
	{"48700000", "Utilidades de paquetes de software"},
	{"48800000", "Sistemas y servidores de información"},
	{"48820000", "Servidores"},
	{"48900000", "Paquetes de software y sistemas informáticos diversos"},
	{"50000000", "Servicios de reparación y mantenimiento"},
	{"50100000", "Servicios de reparación y mantenimiento de vehículos"},
	{"50300000", "Servicios de reparación y mantenimiento de ordenadores, equipo de oficina, telecomunicaciones y audiovisual"},
	{"50320000", "Servicios de reparación y mantenimiento de ordenadores personales"},
	{"50330000", "Servicios de mantenimiento de equipo de telecomunicaciones"},
	{"50340000", "Servicios de reparación y mantenimiento de equipo audiovisual y óptico"},
	{"50400000", "Servicios de reparación y mantenimiento de equipo médico y de precisión"},
	{"50413200", "Servicios de reparación y mantenimiento de equipo contra incendios"},
	{"50600000", "Servicios de reparación y mantenimiento de material de seguridad y defensa"},
	{"50610000", "Servicios de reparación y mantenimiento de equipo de seguridad"},
	{"50700000", "Servicios de reparación y mantenimiento de equipos de edificios"},
	{"50710000", "Servicios de reparación y mantenimiento de equipos eléctricos y mecánicos de edificios"},
	{"50711000", "Servicios de reparación y mantenimiento de equipos eléctricos de edificios"},
	{"50712000", "Servicios de reparación y mantenimiento de equipos mecánicos de edificios"},
	{"50720000", "Servicios de reparación y mantenimiento de calefacción central"},
	{"50730000", "Servicios de reparación y mantenimiento de grupos refrigeradores"},
	{"50750000", "Servicios de mantenimiento de ascensores"},
	{"50800000", "Servicios de reparación y mantenimiento varios"},
	{"55000000", "Servicios comerciales al por menor de hostelería"},
	{"55500000", "Servicios de cantina y comedor"},
	{"55520000", "Servicios de suministro de comidas"},
	{"55523000", "Servicios de suministro de comidas para otras empresas e instituciones"},
	{"55524000", "Servicios de suministro de comidas para escuelas"},
	{"60000000", "Servicios de transporte (excluido el transporte de residuos)"},
	{"60100000", "Servicios de transporte por carretera"},
	{"60112000", "Servicios de transporte público por carretera"},
	{"60130000", "Servicios especiales de transporte de pasajeros por carretera"},
	{"60140000", "Transporte no regular de pasajeros"},
	{"64000000", "Servicios de correos y telecomunicaciones"},
	{"64100000", "Servicios postales y de correo rápido"},
	{"64200000", "Servicios de telecomunicaciones"},
	{"64210000", "Servicios telefónicos y de transmisión de datos"},
	{"64212000", "Servicios de telefonía móvil"},
	{"64216000", "Servicios electrónicos de mensajes e información"},
	{"65000000", "Servicios públicos"},
	{"65100000", "Distribución de agua y servicios conexos"},
	{"65300000", "Distribución de electricidad y servicios conexos"},
	{"66000000", "Servicios financieros y de seguros"},
	{"66500000", "Servicios de seguros"},
	{"66510000", "Servicios de seguros (generales)"},
	{"71000000", "Servicios de arquitectura, construcción, ingeniería e inspección"},
	{"71200000", "Servicios de arquitectura y servicios conexos"},
	{"71240000", "Servicios de arquitectura, ingeniería y planificación"},
	{"71300000", "Servicios de ingeniería"},
	{"71310000", "Servicios de consultoría en ingeniería y construcción"},
	{"71320000", "Servicios de diseño técnico"},
	{"71500000", "Servicios relacionados con la construcción"},
	{"71520000", "Servicios de supervisión de obras"},
	{"71600000", "Servicios de ensayos, análisis y consultoría técnicos"},
	{"72000000", "Servicios TI: consultoría, desarrollo de software, Internet y apoyo"},
	{"72200000", "Servicios de programación de software y de consultoría"},
	{"72210000", "Servicios de programación de paquetes de software"},
	{"72220000", "Servicios de consultoría en sistemas y consultoría técnica"},
	{"72260000", "Servicios relacionados con el software"},
	{"72267000", "Servicios de mantenimiento y reparación de software"},
	{"72300000", "Servicios de datos"},
	{"72400000", "Servicios de Internet"},
	{"72500000", "Servicios informáticos"},
	{"72600000", "Servicios de apoyo informático y de consultoría"},
	{"72700000", "Servicios de red informática"},
	{"72800000", "Servicios de auditoría y de prueba informáticas"},
	{"73000000", "Servicios de investigación y desarrollo y servicios de consultoría conexos"},
	{"73100000", "Servicios de investigación y desarrollo experimental"},
	{"75000000", "Servicios de administración pública, defensa y servicios de seguridad social"},
	{"75100000", "Servicios de administración pública"},
	{"77000000", "Servicios agrícolas, forestales, hortícolas, acuícolas y apícolas"},
	{"77300000", "Servicios de horticultura"},
	{"77310000", "Servicios de plantación y mantenimiento de zonas verdes"},
	{"77311000", "Servicios de mantenimiento de jardines ornamentales y de recreo"},
	{"77313000", "Servicios de mantenimiento de parques"},
	{"79000000", "Servicios a empresas: legislación, mercadotecnia, asesoría, selección de personal, imprenta y seguridad"},
	{"79340000", "Servicios de publicidad y de marketing"},
	{"79400000", "Servicios de consultoría comercial y de gestión y servicios conexos"},
	{"79410000", "Servicios de consultoría comercial y de gestión"},
	{"79700000", "Servicios de investigación y seguridad"},
	{"79710000", "Servicios de seguridad"},
	{"79711000", "Servicios de supervisión de alarmas"},
	{"79713000", "Servicios de guardias de seguridad"},
	{"79714000", "Servicios de vigilancia"},
	{"79800000", "Servicios de impresión y servicios conexos"},
	{"79950000", "Servicios de organización de exposiciones, ferias y congresos"},
	{"80000000", "Servicios de enseñanza y formación"},
	{"80500000", "Servicios de formación"},
	{"85000000", "Servicios de salud y asistencia social"},
	{"85100000", "Servicios de salud"},
	{"85300000", "Servicios de asistencia social y servicios conexos"},
	{"85310000", "Servicios de asistencia social"},
	{"90000000", "Servicios de alcantarillado, eliminación de residuos, limpieza y medioambientales"},
	{"90500000", "Servicios relacionados con desperdicios y residuos"},
	{"90510000", "Eliminación y tratamiento de desperdicios"},
	{"90511000", "Servicios de recogida de desperdicios"},
	{"90600000", "Servicios de limpieza y barrido en zonas urbanas o rurales"},
	{"90610000", "Servicios de limpieza y barrido de calles"},
	{"90900000", "Servicios de limpieza e higienización"},
	{"90910000", "Servicios de limpieza"},
	{"90911000", "Servicios de limpieza de viviendas, edificios y ventanas"},
	{"90911200", "Servicios de limpieza de edificios"},
	{"90919000", "Servicios de limpieza de oficinas, escuelas y equipo de oficina"},
	{"92000000", "Servicios de esparcimiento, culturales y deportivos"},
	{"92300000", "Servicios de entretenimiento"},
	{"98000000", "Otros servicios comunitarios, sociales o personales"},
	{"98300000", "Servicios diversos"},
}

// cpvOfInterest: CPV propuestos para 101.cat (§12.1 del proyecto).
var cpvOfInterest = []string{"35125000", "32323500", "31625200", "35111000", "45343000", "45312000",
	"45314000", "32412000", "64200000", "09332000", "50610000"}

// divisionWeight: peso relativo aproximado de cada división CPV en número de expedientes.
var divisionWeight = map[string]float64{
	"45": 18, "33": 12, "50": 7, "79": 7, "71": 6, "90": 5, "72": 5, "30": 4, "34": 3, "09": 3,
	"15": 3, "85": 3, "92": 3, "48": 2, "55": 2, "60": 2, "80": 2, "77": 2, "39": 2, "44": 2,
	"98": 2, "31": 2, "64": 1.5, "32": 1.5, "35": 1.5, "66": 1, "42": 1, "22": 1, "18": 1,
	"65": 1, "73": 1, "75": 0.5, "03": 0.5,
}

// divisionBaja: baja media (adjudicado frente a presupuesto base) aproximada por división.
var divisionBaja = map[string]float64{
	"45": 0.16, "71": 0.20, "72": 0.12, "79": 0.12, "90": 0.10, "50": 0.12, "33": 0.06,
	"30": 0.08, "09": 0.04, "65": 0.05, "66": 0.07,
}

// significant devuelve el código sin los ceros finales (mínimo 2 dígitos).
func significant(code string) string {
	s := strings.TrimRight(code, "0")
	if len(s) < 2 {
		s = code[:2]
	}
	return s
}

// cpvParent: el código más cercano de la lista que es prefijo significativo del código dado.
func cpvParent(code string, set map[string]bool) string {
	s := significant(code)
	for l := len(s) - 1; l >= 2; l-- {
		cand := s[:l] + strings.Repeat("0", 8-l)
		if cand != code && set[cand] {
			return cand
		}
	}
	return ""
}

type nutsEntry struct {
	Code string
	Name string
	Pop  float64 // millones de habitantes aproximados (NUTS 3)
	Prov string  // código INE de provincia (NUTS 3)
}

var nuts1 = []nutsEntry{{"ES1", "Noroeste", 0, ""}, {"ES2", "Noreste", 0, ""}, {"ES3", "Comunidad de Madrid", 0, ""},
	{"ES4", "Centro", 0, ""}, {"ES5", "Este", 0, ""}, {"ES6", "Sur", 0, ""}, {"ES7", "Canarias", 0, ""}}

var nuts2 = []nutsEntry{{"ES11", "Galicia", 0, "12"}, {"ES12", "Principado de Asturias", 0, "03"}, {"ES13", "Cantabria", 0, "06"},
	{"ES21", "País Vasco", 0, "16"}, {"ES22", "Comunidad Foral de Navarra", 0, "15"}, {"ES23", "La Rioja", 0, "17"},
	{"ES24", "Aragón", 0, "02"}, {"ES30", "Comunidad de Madrid", 0, "13"}, {"ES41", "Castilla y León", 0, "07"},
	{"ES42", "Castilla-La Mancha", 0, "08"}, {"ES43", "Extremadura", 0, "11"}, {"ES51", "Cataluña", 0, "09"},
	{"ES52", "Comunitat Valenciana", 0, "10"}, {"ES53", "Illes Balears", 0, "04"}, {"ES61", "Andalucía", 0, "01"},
	{"ES62", "Región de Murcia", 0, "14"}, {"ES63", "Ceuta", 0, "18"}, {"ES64", "Melilla", 0, "19"}, {"ES70", "Canarias", 0, "05"}}

// nuts3: provincias/islas (NUTS 2021), población aproximada y código INE de provincia.
var nuts3 = []nutsEntry{
	{"ES111", "A Coruña", 1.12, "15"}, {"ES112", "Lugo", 0.33, "27"}, {"ES113", "Ourense", 0.31, "32"}, {"ES114", "Pontevedra", 0.94, "36"},
	{"ES120", "Asturias", 1.01, "33"}, {"ES130", "Cantabria", 0.59, "39"}, {"ES211", "Araba/Álava", 0.33, "01"},
	{"ES212", "Gipuzkoa", 0.73, "20"}, {"ES213", "Bizkaia", 1.15, "48"}, {"ES220", "Navarra", 0.67, "31"}, {"ES230", "La Rioja", 0.32, "26"},
	{"ES241", "Huesca", 0.22, "22"}, {"ES242", "Teruel", 0.13, "44"}, {"ES243", "Zaragoza", 0.97, "50"}, {"ES300", "Madrid", 6.9, "28"},
	{"ES411", "Ávila", 0.16, "05"}, {"ES412", "Burgos", 0.36, "09"}, {"ES413", "León", 0.45, "24"}, {"ES414", "Palencia", 0.16, "34"},
	{"ES415", "Salamanca", 0.33, "37"}, {"ES416", "Segovia", 0.15, "40"}, {"ES417", "Soria", 0.09, "42"}, {"ES418", "Valladolid", 0.52, "47"},
	{"ES419", "Zamora", 0.17, "49"}, {"ES421", "Albacete", 0.39, "02"}, {"ES422", "Ciudad Real", 0.49, "13"}, {"ES423", "Cuenca", 0.20, "16"},
	{"ES424", "Guadalajara", 0.27, "19"}, {"ES425", "Toledo", 0.71, "45"}, {"ES431", "Badajoz", 0.67, "06"}, {"ES432", "Cáceres", 0.39, "10"},
	{"ES511", "Barcelona", 5.7, "08"}, {"ES512", "Girona", 0.79, "17"}, {"ES513", "Lleida", 0.44, "25"}, {"ES514", "Tarragona", 0.83, "43"},
	{"ES521", "Alicante/Alacant", 1.9, "03"}, {"ES522", "Castellón/Castelló", 0.59, "12"}, {"ES523", "Valencia/València", 2.6, "46"},
	{"ES531", "Eivissa y Formentera", 0.16, "07"}, {"ES532", "Mallorca", 0.94, "07"}, {"ES533", "Menorca", 0.10, "07"},
	{"ES611", "Almería", 0.73, "04"}, {"ES612", "Cádiz", 1.25, "11"}, {"ES613", "Córdoba", 0.78, "14"}, {"ES614", "Granada", 0.92, "18"},
	{"ES615", "Huelva", 0.52, "21"}, {"ES616", "Jaén", 0.63, "23"}, {"ES617", "Málaga", 1.7, "29"}, {"ES618", "Sevilla", 1.95, "41"},
	{"ES620", "Murcia", 1.53, "30"}, {"ES630", "Ceuta", 0.08, "51"}, {"ES640", "Melilla", 0.09, "52"}, {"ES703", "El Hierro", 0.01, "38"},
	{"ES704", "Fuerteventura", 0.12, "35"}, {"ES705", "Gran Canaria", 0.86, "35"}, {"ES706", "La Gomera", 0.02, "38"},
	{"ES707", "La Palma", 0.08, "38"}, {"ES708", "Lanzarote", 0.16, "35"}, {"ES709", "Tenerife", 0.93, "38"},
}

var sources = []string{"PLACSP_643", "PLACSP_1044", "TED", "CAT"}

// catalog: estructuras derivadas y precalculadas que comparten generador, cargador y consultas.
type catalog struct {
	cpvSet      map[string]bool
	cpvName     map[string]string
	divisions   []string
	divCum      []float64
	divCodes    map[string][]string
	divCodeCum  map[string][]float64
	nuts3Cum    []float64
	nuts2Index  map[string]int // código NUTS2 -> índice en nuts2
	ccaaOfNuts2 map[string]string
}

func newCatalog() *catalog {
	c := &catalog{cpvSet: map[string]bool{}, cpvName: map[string]string{}, divCodes: map[string][]string{}, divCodeCum: map[string][]float64{},
		nuts2Index: map[string]int{}, ccaaOfNuts2: map[string]string{}}
	for _, e := range cpvList {
		c.cpvSet[e.Code] = true
		c.cpvName[e.Code] = e.Name
		d := e.Code[:2]
		c.divCodes[d] = append(c.divCodes[d], e.Code)
	}
	for d := range divisionWeight {
		if len(c.divCodes[d]) == 0 {
			panic("división sin códigos: " + d)
		}
		c.divisions = append(c.divisions, d)
	}
	sort.Strings(c.divisions)
	acc := 0.0
	for _, d := range c.divisions {
		acc += divisionWeight[d]
		c.divCum = append(c.divCum, acc)
		// Los códigos más específicos se usan más que la raíz de la división.
		a := 0.0
		var cum []float64
		for _, code := range c.divCodes[d] {
			a += float64(len(significant(code)))
			cum = append(cum, a)
		}
		c.divCodeCum[d] = cum
	}
	acc = 0
	for _, n := range nuts3 {
		acc += n.Pop
		c.nuts3Cum = append(c.nuts3Cum, acc)
	}
	for i, n := range nuts2 {
		c.nuts2Index[n.Code] = i
		c.ccaaOfNuts2[n.Code] = n.Prov
	}
	return c
}

// pickCum elige un índice según una tabla de pesos acumulados.
func pickCum(cum []float64, u float64) int {
	x := u * cum[len(cum)-1]
	i := sort.SearchFloat64s(cum, x)
	if i >= len(cum) {
		i = len(cum) - 1
	}
	return i
}

func bajaMean(div string) float64 {
	if b, ok := divisionBaja[div]; ok {
		return b
	}
	return 0.10
}
