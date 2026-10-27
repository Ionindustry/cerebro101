package placsp

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/ionindustry/cerebro101/licitaciones/internal/domain"
)

var (
	decimalRe = regexp.MustCompile(`^-?\d+(\.\d+)?$`)
	dateRe    = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}`)
	numericID = regexp.MustCompile(`(\d+)/?$`)
)

// conv acumula los avisos de calidad de datos de una entrada.
type conv struct {
	warnings []string
	loc      *time.Location
}

func (c *conv) warn(format string, a ...any) {
	c.warnings = append(c.warnings, fmt.Sprintf(format, a...))
}

func (e *xmlEntry) toDomain(source string, loc *time.Location) *domain.Licitacion {
	c := &conv{loc: loc}
	l := &domain.Licitacion{Source: source, SourceID: strings.TrimSpace(e.ID), Title: clean(e.Title)}
	if m := numericID.FindStringSubmatch(l.SourceID); m != nil {
		l.NumericID = m[1]
	}
	for _, k := range e.Links {
		if k.Rel == "" || k.Rel == "alternate" {
			l.Link = k.Href
			break
		}
	}
	if t, err := time.Parse(time.RFC3339Nano, strings.TrimSpace(e.Updated)); err == nil {
		l.Updated = t
	} else {
		c.warn("atom:updated no válido: %q", e.Updated)
	}
	if e.CFS == nil {
		c.warn("la entrada no trae ContractFolderStatus")
		l.Warnings = c.warnings
		return l
	}
	s := e.CFS
	l.Expediente = clean(s.FolderID)
	l.Status = clean(s.Status)
	for _, u := range s.UUIDs {
		if u.Scheme == "TED" {
			l.TEDProcedureID = clean(u.Value)
		}
	}
	l.Organism = c.organization(s.Party)

	p := s.Project
	if l.Title == "" {
		l.Title = clean(p.Name)
	}
	l.ContractType, l.ContractSubType = clean(p.Type), clean(p.SubType)
	l.EstimatedValue = c.money("valor estimado", p.Budget.Estimated)
	l.BaseBudgetExclVAT = c.money("presupuesto base sin IVA", p.Budget.Excl)
	l.BaseBudgetInclVAT = c.money("presupuesto base con IVA", p.Budget.Total)
	l.CPV, l.NUTS = codes(p.CPVs), codes(p.NUTS)
	if p.Duration != nil && clean(p.Duration.Value) != "" {
		l.Duration = &domain.Duration{Value: clean(p.Duration.Value), Unit: clean(p.Duration.Unit)}
	}

	l.Procedure, l.Urgency, l.System = clean(s.Process.Procedure), clean(s.Process.Urgency), clean(s.Process.System)
	l.OverThreshold = c.boolean("OverThresholdIndicator", s.Process.OverThreshold)
	l.TenderDeadline = c.deadline(s.Process.DeadlineDate, s.Process.DeadlineTime)
	l.Funding = clean(s.Terms.Funding)

	for _, n := range s.Notices {
		l.Notices = append(l.Notices, domain.Notice{Type: clean(n.Type), PublishedOn: c.date("fecha de publicación", n.On), Media: clean(n.Media)})
	}
	for _, k := range s.Terms.Criteria {
		l.Criteria = append(l.Criteria, domain.AwardCriterion{Type: clean(k.Type), SubType: clean(k.SubType), Description: clean(k.Description), Weight: clean(k.Weight)})
	}
	for _, lot := range s.Lots {
		l.Lots = append(l.Lots, domain.Lot{
			ID: clean(lot.ID.Value), Name: clean(lot.Project.Name),
			BaseBudgetExclVAT: c.money("presupuesto del lote sin IVA", lot.Project.Budget.Excl),
			BaseBudgetInclVAT: c.money("presupuesto del lote con IVA", lot.Project.Budget.Total),
			CPV:               codes(lot.Project.CPVs), NUTS: codes(lot.Project.NUTS),
		})
	}
	for _, r := range s.Results {
		l.Results = append(l.Results, c.result(r))
	}
	for _, m := range s.Mods {
		l.Modifications = append(l.Modifications, domain.Modification{
			ID: clean(m.ID), ContractID: clean(m.ContractID), Note: clean(m.Note),
			AmountExclVAT: c.money("importe de la modificación", m.Amount), FinalExclVAT: c.money("importe tras la modificación", m.Final),
		})
	}
	l.Documents = append(l.Documents, documents("legal", s.Legal)...)
	l.Documents = append(l.Documents, documents("technical", s.Tech)...)
	l.Documents = append(l.Documents, documents("additional", s.Extra)...)
	l.Warnings = c.warnings
	return l
}

func (c *conv) organization(p xmlParty) domain.Organization {
	o := domain.Organization{Name: clean(p.Party.Name), PartyType: clean(p.TypeCode), Activities: codes(p.Activities)}
	for _, id := range p.Party.IDs {
		v := clean(id.Value)
		switch id.Scheme {
		case "NIF":
			o.NIF = v
		case "DIR3":
			o.DIR3 = v
		case "ID_PLATAFORMA", "ID_OC_PLAT":
			o.PlatformID = v
		}
	}
	if len(p.Party.AgentIDs) > 0 {
		o.AggregatorID = clean(p.Party.AgentIDs[0].Value)
	}
	for q := p.Parent; q != nil; q = q.Parent {
		if n := clean(q.Name); n != "" {
			o.Parents = append(o.Parents, n)
		}
	}
	return o
}

func (c *conv) result(r xmlResult) domain.Result {
	out := domain.Result{
		LotID: clean(r.LotID), Code: clean(r.Code), Description: clean(r.Description),
		WinnerName: clean(r.WinnerName), WinnerIsSME: c.boolean("SMEAwardedIndicator", r.SMEAwarded),
		AwardedExclVAT: c.money("importe adjudicado sin IVA", r.Excl), AwardedInclVAT: c.money("importe adjudicado con IVA", r.Payable),
		LowestOffer: c.money("oferta más baja", r.Lower), HighestOffer: c.money("oferta más alta", r.Higher),
		AbnormallyLow: c.boolean("AbnormallyLowTendersIndicator", r.AbnormalLow),
		AwardDate:     c.date("fecha de adjudicación", r.AwardDate), FormalizedOn: c.date("fecha de formalización", r.ContractOn),
		ContractNumber: clean(r.ContractID), ContractStartsOn: c.date("entrada en vigor", r.StartDate),
	}
	if len(r.WinnerIDs) > 0 {
		out.WinnerID, out.WinnerScheme = clean(r.WinnerIDs[0].Value), clean(r.WinnerIDs[0].Scheme)
	}
	if v := clean(r.Received); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			out.TendersReceived = &n
		} else {
			c.warn("nº de ofertas no válido: %q", v)
		}
	}
	return out
}

// money valida el importe sin pasar por coma flotante; un importe ilegible se descarta con aviso.
func (c *conv) money(what string, a *xmlAmount) *domain.Money {
	if a == nil {
		return nil
	}
	v := clean(a.Value)
	if v == "" {
		return nil
	}
	if !decimalRe.MatchString(v) {
		c.warn("%s no válido: %q", what, v)
		return nil
	}
	if clean(a.Currency) == "" {
		c.warn("%s sin moneda", what)
	}
	return &domain.Money{Value: v, Currency: clean(a.Currency)}
}

// date acepta «AAAA-MM-DD» con o sin zona («2026-04-09+02:00»); descarta lo que no encaje.
func (c *conv) date(what, v string) domain.Date {
	v = clean(v)
	if v == "" {
		return ""
	}
	if !dateRe.MatchString(v) {
		c.warn("%s no válida: %q", what, v)
		return ""
	}
	d := v[:10]
	if _, err := time.Parse("2006-01-02", d); err != nil {
		c.warn("%s no válida: %q", what, v)
		return ""
	}
	return domain.Date(d)
}

func (c *conv) boolean(what, v string) *bool {
	switch clean(v) {
	case "":
		return nil
	case "true", "1":
		t := true
		return &t
	case "false", "0":
		f := false
		return &f
	}
	c.warn("%s no válido: %q", what, v)
	return nil
}

// deadline une EndDate y EndTime. Sin zona en la hora, se interpreta en Europe/Madrid.
func (c *conv) deadline(date, clock string) *time.Time {
	d := c.date("plazo de ofertas", date)
	if d == "" {
		return nil
	}
	clock = clean(clock)
	if clock == "" {
		t, _ := time.ParseInLocation("2006-01-02", string(d), c.loc)
		return &t
	}
	for _, layout := range []string{"2006-01-02T15:04:05.999999999Z07:00", "2006-01-02T15:04:05.999999999"} {
		if t, err := time.ParseInLocation(layout, string(d)+"T"+clock, c.loc); err == nil {
			return &t
		}
	}
	c.warn("hora del plazo de ofertas no válida: %q", clock)
	return nil
}

func documents(kind string, in []xmlDocument) []domain.Document {
	var out []domain.Document
	for _, d := range in {
		out = append(out, domain.Document{Kind: kind, Name: clean(d.Name), URI: clean(d.URI), Hash: clean(d.Hash)})
	}
	return out
}

func codes(in []string) []string {
	var out []string
	for _, s := range in {
		if v := clean(s); v != "" {
			out = append(out, v)
		}
	}
	return out
}

func clean(s string) string { return strings.Join(strings.Fields(s), " ") }
