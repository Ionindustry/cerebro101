package placsp

// Estructuras de lectura del CODICE de PLACSP. Las etiquetas usan solo el nombre local (sin espacio de nombres): en CODICE los
// nombres de un mismo camino no se repiten entre espacios de nombres, y así el parser no depende de los prefijos del documento.
// No se leen los datos de contacto de personas (Contact): minimización de datos.

type xmlLink struct {
	Href string `xml:"href,attr"`
	Rel  string `xml:"rel,attr"`
}

type xmlAmount struct {
	Value    string `xml:",chardata"`
	Currency string `xml:"currencyID,attr"`
}

type xmlScheme struct {
	Value  string `xml:",chardata"`
	Scheme string `xml:"schemeName,attr"`
}

type xmlEntry struct {
	ID      string    `xml:"id"`
	Links   []xmlLink `xml:"link"`
	Title   string    `xml:"title"`
	Updated string    `xml:"updated"`
	CFS     *xmlCFS   `xml:"ContractFolderStatus"`
}

type xmlCFS struct {
	FolderID string      `xml:"ContractFolderID"`
	Status   string      `xml:"ContractFolderStatusCode"`
	UUIDs    []xmlScheme `xml:"UUID"`

	Party   xmlParty      `xml:"LocatedContractingParty"`
	Project xmlProject    `xml:"ProcurementProject"`
	Lots    []xmlLot      `xml:"ProcurementProjectLot"`
	Results []xmlResult   `xml:"TenderResult"`
	Mods    []xmlMod      `xml:"ContractModification"`
	Terms   xmlTerms      `xml:"TenderingTerms"`
	Process xmlProcess    `xml:"TenderingProcess"`
	Notices []xmlNotice   `xml:"ValidNoticeInfo"`
	Legal   []xmlDocument `xml:"LegalDocumentReference"`
	Tech    []xmlDocument `xml:"TechnicalDocumentReference"`
	Extra   []xmlDocument `xml:"AdditionalDocumentReference"`
}

type xmlParty struct {
	TypeCode   string         `xml:"ContractingPartyTypeCode"`
	Activities []string       `xml:"ActivityCode"`
	Party      xmlPartyDetail `xml:"Party"`
	Parent     *xmlParent     `xml:"ParentLocatedParty"`
}

type xmlPartyDetail struct {
	IDs      []xmlScheme `xml:"PartyIdentification>ID"`
	Name     string      `xml:"PartyName>Name"`
	AgentIDs []xmlScheme `xml:"AgentParty>PartyIdentification>ID"`
}

type xmlParent struct {
	Name   string     `xml:"PartyName>Name"`
	Parent *xmlParent `xml:"ParentLocatedParty"`
}

type xmlProject struct {
	Name     string       `xml:"Name"`
	Type     string       `xml:"TypeCode"`
	SubType  string       `xml:"SubTypeCode"`
	Budget   xmlBudget    `xml:"BudgetAmount"`
	CPVs     []string     `xml:"RequiredCommodityClassification>ItemClassificationCode"`
	NUTS     []string     `xml:"RealizedLocation>CountrySubentityCode"`
	Duration *xmlDuration `xml:"PlannedPeriod>DurationMeasure"`
	// Prórrogas previstas: texto libre del pliego («Cabe la opción de tres (3) prórrogas de un (1) año cada una»).
	Extension string `xml:"ContractExtension>OptionValidityPeriod>Description"`
}

type xmlDuration struct {
	Value string `xml:",chardata"`
	Unit  string `xml:"unitCode,attr"`
}

type xmlBudget struct {
	Estimated *xmlAmount `xml:"EstimatedOverallContractAmount"`
	Total     *xmlAmount `xml:"TotalAmount"`
	Excl      *xmlAmount `xml:"TaxExclusiveAmount"`
}

type xmlLot struct {
	ID      xmlScheme  `xml:"ID"`
	Project xmlProject `xml:"ProcurementProject"`
}

type xmlResult struct {
	Code        string      `xml:"ResultCode"`
	Description string      `xml:"Description"`
	AwardDate   string      `xml:"AwardDate"`
	Received    string      `xml:"ReceivedTenderQuantity"`
	Lower       *xmlAmount  `xml:"LowerTenderAmount"`
	Higher      *xmlAmount  `xml:"HigherTenderAmount"`
	AbnormalLow string      `xml:"AbnormallyLowTendersIndicator"`
	SMEAwarded  string      `xml:"SMEAwardedIndicator"`
	StartDate   string      `xml:"StartDate"`
	ContractID  string      `xml:"Contract>ID"`
	ContractOn  string      `xml:"Contract>IssueDate"`
	WinnerIDs   []xmlScheme `xml:"WinningParty>PartyIdentification>ID"`
	WinnerName  string      `xml:"WinningParty>PartyName>Name"`
	LotID       string      `xml:"AwardedTenderedProject>ProcurementProjectLotID"`
	Excl        *xmlAmount  `xml:"AwardedTenderedProject>LegalMonetaryTotal>TaxExclusiveAmount"`
	Payable     *xmlAmount  `xml:"AwardedTenderedProject>LegalMonetaryTotal>PayableAmount"`
}

type xmlMod struct {
	ID         string     `xml:"ID"`
	ContractID string     `xml:"ContractID"`
	Note       string     `xml:"Note"`
	Amount     *xmlAmount `xml:"ContractModificationLegalMonetaryTotal>TaxExclusiveAmount"`
	Final      *xmlAmount `xml:"FinalLegalMonetaryTotal>TaxExclusiveAmount"`
}

type xmlTerms struct {
	Funding  string        `xml:"FundingProgramCode"`
	Criteria []xmlCriteria `xml:"AwardingTerms>AwardingCriteria"`
}

type xmlCriteria struct {
	Type        string `xml:"AwardingCriteriaTypeCode"`
	SubType     string `xml:"AwardingCriteriaSubTypeCode"`
	Description string `xml:"Description"`
	Weight      string `xml:"WeightNumeric"`
}

type xmlProcess struct {
	Procedure     string `xml:"ProcedureCode"`
	Urgency       string `xml:"UrgencyCode"`
	System        string `xml:"ContractingSystemCode"`
	OverThreshold string `xml:"OverThresholdIndicator"`
	DeadlineDate  string `xml:"TenderSubmissionDeadlinePeriod>EndDate"`
	DeadlineTime  string `xml:"TenderSubmissionDeadlinePeriod>EndTime"`
}

type xmlNotice struct {
	Type  string `xml:"NoticeTypeCode"`
	Media string `xml:"AdditionalPublicationStatus>PublicationMediaName"`
	On    string `xml:"AdditionalPublicationStatus>AdditionalPublicationDocumentReference>IssueDate"`
}

type xmlDocument struct {
	Name string `xml:"ID"`
	URI  string `xml:"Attachment>ExternalReference>URI"`
	Hash string `xml:"Attachment>ExternalReference>DocumentHash"`
}

type xmlDeleted struct {
	Ref     string `xml:"ref,attr"`
	When    string `xml:"when,attr"`
	Comment struct {
		Type string `xml:"type,attr"`
	} `xml:"comment"`
}
