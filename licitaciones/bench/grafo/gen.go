package main

// Generador sintético reproducible. Todo depende de la semilla: el expediente i se genera siempre igual con un
// generador propio (PCG(semilla, i)), así que la carga, las consultas y los parámetros pueden regenerar cualquier
// parte del conjunto sin guardarlo en disco.

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"math/rand/v2"
	"time"
)

const (
	nBuyers  = 20000
	nFirms   = 150000
	histDays = 1826 // 5 años de histórico
)

type org struct {
	ID    string // clave estable: DIR3:xxx (comprador) o NIF:xxx (empresa)
	NIF   string
	DIR3  string
	Name  string
	Kind  string // buyer | company
	Type  string // local, autonomico, estatal, universidad | SA, SL, autonomo, UTE
	Nuts3 int
}

type world struct {
	seed   uint64
	today  time.Time
	cat    *catalog
	buyers []org
	firms  []org
	// empresas especializadas por división, y por división y NUTS2 (en orden de tamaño)
	firmsByDiv    map[string][]int32
	firmsByDivReg map[string][]int32 // clave div+"|"+nuts2
}

func cifControl(letter byte, digits string) string {
	sum := 0
	for i := 0; i < 7; i++ {
		d := int(digits[i] - '0')
		if i%2 == 1 { // posiciones pares (2,4,6)
			sum += d
		} else {
			dd := d * 2
			sum += dd/10 + dd%10
		}
	}
	c := (10 - sum%10) % 10
	switch letter {
	case 'P', 'Q', 'R', 'S', 'N', 'W':
		return string("JABCDEFGHI"[c])
	default:
		return fmt.Sprint(c)
	}
}

func dniLetter(n int) string { return string("TRWAGMYFPDXBNJZSQVHLCKE"[n%23]) }

var nameWords = []string{"Ibérica", "Levante", "Norte", "Mediterránea", "Atlántica", "Técnica", "Integral", "Global",
	"Servicios", "Sistemas", "Instalaciones", "Obras", "Proyectos", "Ingeniería", "Seguridad", "Soluciones", "Energía",
	"Mantenimientos", "Construcciones", "Telecom", "Datos", "Gestión", "Ambiental", "Sanitaria", "Logística", "Digital"}

func newWorld(seed uint64, today time.Time) *world {
	w := &world{seed: seed, today: today, cat: newCatalog(), firmsByDiv: map[string][]int32{}, firmsByDivReg: map[string][]int32{}}
	r := rand.New(rand.NewPCG(seed, 0xB0B0))
	c := w.cat
	pickNuts3 := func() int { return pickCum(c.nuts3Cum, r.Float64()) }
	madrid := 0
	for i, n := range nuts3 {
		if n.Code == "ES300" {
			madrid = i
		}
	}
	// Compradores: índice bajo = mayor volumen (los grandes son estatales y autonómicos).
	seqLocal := map[string]int{}
	seqA, seqE, seqU := 0, 0, 0
	for i := 0; i < nBuyers; i++ {
		u := r.Float64()
		var t string
		if i < 2000 {
			switch {
			case u < 0.30:
				t = "estatal"
			case u < 0.80:
				t = "autonomico"
			case u < 0.85:
				t = "universidad"
			default:
				t = "local"
			}
		} else {
			switch {
			case u < 0.05:
				t = "estatal"
			case u < 0.25:
				t = "autonomico"
			case u < 0.27:
				t = "universidad"
			default:
				t = "local"
			}
		}
		n3 := pickNuts3()
		if t == "estatal" && r.Float64() < 0.7 {
			n3 = madrid
		}
		ne := nuts3[n3]
		ccaa := c.ccaaOfNuts2[ne.Code[:4]]
		var dir3, nif, name string
		switch t {
		case "local":
			s := seqLocal[ne.Prov]
			seqLocal[ne.Prov] = s + 1
			dir3 = fmt.Sprintf("L01%s%04d", ne.Prov, s)
			d := fmt.Sprintf("%s%05d", ne.Prov, s)
			nif = "P" + d + cifControl('P', d)
			name = fmt.Sprintf("Ayuntamiento %s %d", ne.Name, s+1)
		case "autonomico":
			seqA++
			dir3 = fmt.Sprintf("A%s%06d", ccaa, seqA)
			d := fmt.Sprintf("%07d", 1000000+seqA)
			nif = "S" + d + cifControl('S', d)
			name = fmt.Sprintf("Departamento %d de %s", seqA, nuts2[c.nuts2Index[ne.Code[:4]]].Name)
		case "estatal":
			seqE++
			dir3 = fmt.Sprintf("E%08d", seqE)
			d := fmt.Sprintf("28%05d", seqE)
			nif = "S" + d + cifControl('S', d)
			name = fmt.Sprintf("Organismo estatal %d", seqE)
		default:
			seqU++
			dir3 = fmt.Sprintf("U%08d", seqU)
			d := fmt.Sprintf("%s%05d", ne.Prov, 50000+seqU)
			nif = "Q" + d + cifControl('Q', d)
			name = fmt.Sprintf("Universidad %d (%s)", seqU, ne.Name)
		}
		w.buyers = append(w.buyers, org{ID: "DIR3:" + dir3, NIF: nif, DIR3: dir3, Name: name, Kind: "buyer", Type: t, Nuts3: n3})
	}
	// Empresas: índice bajo = empresa grande (gana más en todas partes: cola larga).
	seqB := map[string]int{}
	for i := 0; i < nFirms; i++ {
		u := r.Float64()
		var t string
		if i < 1500 {
			if u < 0.5 {
				t = "SA"
			} else {
				t = "SL"
			}
		} else {
			switch {
			case u < 0.78:
				t = "SL"
			case u < 0.90:
				t = "autonomo"
			case u < 0.96:
				t = "SA"
			default:
				t = "UTE"
			}
		}
		n3 := pickNuts3()
		ne := nuts3[n3]
		var nif string
		switch t {
		case "autonomo":
			n := 12000000 + i*3
			nif = fmt.Sprintf("%08d%s", n, dniLetter(n))
		default:
			l := map[string]byte{"SA": 'A', "SL": 'B', "UTE": 'U'}[t]
			k := string(l) + ne.Prov
			s := seqB[k]
			seqB[k] = s + 1
			d := fmt.Sprintf("%s%05d", ne.Prov, s)
			nif = string(l) + d + cifControl(l, d)
		}
		name := fmt.Sprintf("%s %s %d %s", nameWords[r.IntN(len(nameWords))], nameWords[r.IntN(len(nameWords))], i, t)
		if t == "autonomo" {
			name = fmt.Sprintf("Persona física %d", i)
		}
		w.firms = append(w.firms, org{ID: "NIF:" + nif, NIF: nif, Name: name, Kind: "company", Type: t, Nuts3: n3})
		// especialización: 1 división principal y, a veces, una segunda
		nd := 1
		if r.Float64() < 0.4 {
			nd = 2
		}
		seen := map[string]bool{}
		for k := 0; k < nd; k++ {
			d := c.divisions[pickCum(c.divCum, r.Float64())]
			if seen[d] {
				continue
			}
			seen[d] = true
			w.firmsByDiv[d] = append(w.firmsByDiv[d], int32(i))
			key := d + "|" + ne.Code[:4]
			w.firmsByDivReg[key] = append(w.firmsByDivReg[key], int32(i))
		}
	}
	return w
}

// zipfPick: índice en [0,n) con cola larga (s=1.2, v=30): el 1 % superior se lleva ~la mitad.
func zipfPick(r *rand.Rand, n int) int {
	if n <= 1 {
		return 0
	}
	return int(rand.NewZipf(r, 1.2, 30, uint64(n-1)).Uint64())
}

type bid struct {
	Firm   int
	Oferta float64
	Baja   float64
	Winner bool
}

type award struct {
	ID       string
	Firm     int
	Importe  float64
	ImporteI float64 // con IVA
	Baja     float64
	Fecha    time.Time
	Formal   time.Time // cero si no hay formalización
	End      time.Time
	NOfertas int
}

type lot struct {
	ID      string
	Num     int
	CPV     string
	Budget  float64
	Award   *award
	Bidders []bid // solo cuando el acta publica los licitadores
}

type version struct {
	ID        string
	N         int
	Published time.Time
	Hash      string
}

type notice struct {
	ID       string
	Type     string
	Date     time.Time
	Versions []version
}

type procedure struct {
	Idx        int
	ID         string
	Source     string
	Expediente string
	Title      string
	Buyer      int
	CPV        string
	Nuts3      int
	Date       time.Time
	Deadline   time.Time
	Budget     float64
	ProcType   string
	Status     string
	Lots       []lot
	Notices    []notice
	AwardNotic string // id del anuncio de adjudicación (DERIVED_FROM de Award)
}

var procTypes = []string{"abierto", "abierto", "abierto", "abierto_simplificado", "abierto_simplificado", "negociado_sin_publicidad", "restringido", "basado_en_acuerdo_marco"}

func (w *world) pickFirm(r *rand.Rand, div, nuts2 string) int {
	u := r.Float64()
	if u < 0.55 {
		if l := w.firmsByDivReg[div+"|"+nuts2]; len(l) > 0 {
			return int(l[zipfPick(r, len(l))])
		}
	}
	if u < 0.85 {
		if l := w.firmsByDiv[div]; len(l) > 0 {
			return int(l[zipfPick(r, len(l))])
		}
	}
	return zipfPick(r, nFirms)
}

func clamp(x, lo, hi float64) float64 { return math.Max(lo, math.Min(hi, x)) }

func day(t time.Time, d int) time.Time { return t.AddDate(0, 0, d) }

func hashOf(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

// proc genera el expediente idx de forma determinista.
func (w *world) proc(idx int) *procedure {
	r := rand.New(rand.NewPCG(w.seed, uint64(idx)+1))
	c := w.cat
	p := &procedure{Idx: idx}
	p.Buyer = int(rand.NewZipf(r, 1.1, 10, nBuyers-1).Uint64())
	b := w.buyers[p.Buyer]
	div := c.divisions[pickCum(c.divCum, r.Float64())]
	codes := c.divCodes[div]
	p.CPV = codes[pickCum(c.divCodeCum[div], r.Float64())]
	p.Nuts3 = b.Nuts3
	if r.Float64() < 0.10 {
		p.Nuts3 = pickCum(c.nuts3Cum, r.Float64())
	}
	nutsCode := nuts3[p.Nuts3].Code
	n2 := nutsCode[:4]
	daysAgo := int(float64(histDays) * (1 - math.Sqrt(r.Float64()))) // más reciente = más frecuente
	p.Date = day(w.today, -daysAgo)
	p.Deadline = day(p.Date, 15+r.IntN(38))
	budget := math.Exp(math.Log(40000) + 1.4*r.NormFloat64())
	if div == "45" {
		budget *= 2
	}
	p.Budget = math.Round(clamp(budget, 1000, 50e6)*100) / 100
	p.ProcType = procTypes[r.IntN(len(procTypes))]
	// fuente
	u := r.Float64()
	switch {
	case n2 == "ES51" && u < 0.5:
		p.Source = "CAT"
	case p.Budget > 215000 && u < 0.3:
		p.Source = "TED"
	case u < 0.75:
		p.Source = "PLACSP_643"
	default:
		p.Source = "PLACSP_1044"
	}
	p.Expediente = fmt.Sprintf("%d/%07d", p.Date.Year(), idx)
	p.ID = p.Source + ":" + p.Expediente
	p.Title = fmt.Sprintf("%s — %s", c.nameOf(p.CPV), b.Name)

	// lotes
	nl := 1
	if r.Float64() >= 0.8 {
		nl = 2 + int(r.ExpFloat64()*1.5)
		if nl > 30 {
			nl = 30
		}
	}
	annulled := r.Float64() < 0.03
	awardDate := day(p.Deadline, 15+r.IntN(105))
	awarded := !annulled && !awardDate.After(w.today)
	baseBaja := bajaMean(div)
	weights := make([]float64, nl)
	tot := 0.0
	for i := range weights {
		weights[i] = 0.5 + r.Float64()
		tot += weights[i]
	}
	anyAward := false
	var lastFormal time.Time
	for i := 0; i < nl; i++ {
		l := lot{ID: fmt.Sprintf("%s#L%d", p.ID, i+1), Num: i + 1, CPV: p.CPV}
		if r.Float64() < 0.3 {
			l.CPV = codes[r.IntN(len(codes))]
		}
		l.Budget = math.Round(p.Budget*weights[i]/tot*100) / 100
		if awarded && r.Float64() >= 0.05 { // 5 % desiertos
			anyAward = true
			nOf := 1 + int(r.ExpFloat64()*2.5)
			if nOf > 40 {
				nOf = 40
			}
			win := w.pickFirm(r, div, n2)
			wb := clamp(baseBaja+0.08*r.NormFloat64(), 0, 0.6)
			if nOf == 1 {
				wb = clamp(0.02*r.Float64(), 0, 0.6)
			}
			a := &award{ID: l.ID + "#A", Firm: win, Baja: math.Round(wb*10000) / 10000, NOfertas: nOf, Fecha: awardDate}
			a.Importe = math.Round(l.Budget*(1-a.Baja)*100) / 100
			a.ImporteI = math.Round(a.Importe*1.21*100) / 100
			formal := day(awardDate, 10+r.IntN(35))
			if !formal.After(w.today) {
				a.Formal = formal
				lastFormal = formal
			}
			months := []int{6, 12, 12, 24, 24, 36, 48}[r.IntN(7)]
			start := formal
			a.End = start.AddDate(0, months, 0)
			l.Award = a
			if r.Float64() < 0.4 { // el acta publica los licitadores
				l.Bidders = append(l.Bidders, bid{Firm: win, Oferta: a.Importe, Baja: a.Baja, Winner: true})
				seen := map[int]bool{win: true}
				for k := 1; k < nOf; k++ {
					f := w.pickFirm(r, div, n2)
					if seen[f] {
						continue
					}
					seen[f] = true
					bb := wb - math.Abs(0.05*r.NormFloat64())
					if r.Float64() < 0.3 {
						bb = wb + math.Abs(0.04*r.NormFloat64()) // perdió por calidad
					}
					bb = clamp(bb, 0, 0.7)
					l.Bidders = append(l.Bidders, bid{Firm: f, Oferta: math.Round(l.Budget*(1-bb)*100) / 100, Baja: math.Round(bb*10000) / 10000})
				}
			}
		}
		p.Lots = append(p.Lots, l)
	}
	switch {
	case annulled:
		p.Status = "anulada"
	case anyAward:
		p.Status = "adjudicada"
	case awarded:
		p.Status = "desierta"
	case p.Deadline.After(w.today):
		p.Status = "abierta"
	default:
		p.Status = "en_evaluacion"
	}
	// anuncios y versiones
	addNotice := func(t string, d time.Time) string {
		if d.After(w.today) {
			return ""
		}
		n := notice{ID: fmt.Sprintf("%s#N%d", p.ID, len(p.Notices)+1), Type: t, Date: d}
		nv := 1
		if r.Float64() < 0.2 {
			nv = 2
			if r.Float64() < 0.25 {
				nv = 3
			}
		}
		pub := d
		for k := 1; k <= nv; k++ {
			if pub.After(w.today) {
				break
			}
			vid := fmt.Sprintf("%s#v%d", n.ID, k)
			n.Versions = append(n.Versions, version{ID: vid, N: k, Published: pub, Hash: hashOf(vid)})
			pub = day(pub, 1+r.IntN(20))
		}
		p.Notices = append(p.Notices, n)
		return n.ID
	}
	if r.Float64() < 0.10 {
		addNotice("anuncio_previo", day(p.Date, -30-r.IntN(60)))
	}
	addNotice("licitacion", p.Date)
	if annulled {
		addNotice("anulacion", day(p.Date, 5+r.IntN(30)))
	}
	if anyAward {
		p.AwardNotic = addNotice("adjudicacion", awardDate)
		if !lastFormal.IsZero() {
			addNotice("formalizacion", lastFormal)
			if r.Float64() < 0.05 {
				if m := day(lastFormal, 60+r.IntN(300)); !m.After(w.today) {
					addNotice("modificacion", m)
				}
			}
		}
	}
	return p
}

func (c *catalog) nameOf(code string) string {
	if n, ok := c.cpvName[code]; ok {
		return n
	}
	return code
}
