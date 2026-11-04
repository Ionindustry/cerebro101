-- Si la fuente está AL DÍA: las páginas ya ingeridas forman una cadena sin huecos desde la cabecera (ingest.AlDia). Tras una parada (equipo apagado), el ingestor se pone al día de lo más nuevo hacia
-- atrás y esto vale false hasta que acaba; el panel lo enseña como «poniéndose al día». Lo que ya existía se da por al día.
ALTER TABLE puntos_control ADD COLUMN al_dia boolean NOT NULL DEFAULT true;
