# Datos de la sociedad en ERPNext (para rellenar las plantillas y el DEUC)

Las plantillas de una oferta (declaración responsable, anexos, DEUC…) se rellenan **solo con lo que hay en ERPNext**. Lo que falta queda como hueco, y la revisión previa de la oferta («Revisar antes de preparar la oferta») dice cuáles son. Esta hoja es el listado completo de lo que hay que cargar **una sola vez** para cada sociedad que presenta ofertas (hoy, **«101»**).

Se carga en `http://localhost:8081` (ERPNext). Nada de esto sale del servidor: el Cerebro solo lo **lee**, con un usuario técnico de solo lectura (`licitaciones`).

---

## 1. Tu hoja: qué datos reunir

Rellena la columna «Tu valor» (en papel, en un Excel, donde quieras) y luego cópialo en ERPNext siguiendo el apartado 2.

| # | Dato | Dónde va en ERPNext | Ejemplo | Tu valor |
|---|------|---------------------|---------|----------|
| 1 | **Razón social** | Company → *Company Name* | `101 Servicios Tecnológicos, S.L.` | |
| 2 | **NIF/CIF** | Company → *Tax ID* | `B12345678` | |
| 3 | **Teléfono** | Company → *Phone No* | `972 000 000` | |
| 4 | **Correo** | Company → *Email* | `administracion@101.cat` | |
| 5 | **País** | Company → *Country* | `Spain` | |
| 6 | **Datos de inscripción en el Registro Mercantil** | Company → *Registration Details* | `Inscrita en el Registro Mercantil de Girona, Tomo 3000, Folio 1, Hoja GI-00000, Inscripción 1.ª` | |
| 7 | **Domicilio** (calle y número) | Address → *Address Line 1* | `Carrer Major, 1, 2n 1a` | |
| 8 | **Código postal** | Address → *Postal Code* | `17001` | |
| 9 | **Localidad** | Address → *City/Town* | `Girona` | |
| 10 | **Provincia** | Address → *State/Province* | `Girona` | |
| 11 | **País de la dirección** | Address → *Country* | `Spain` | |
| 12 | **Nombre y apellidos del representante** | Contact → *First Name* y *Last Name* | `Albert Apellido` | |
| 13 | **Cargo del representante** | Contact → *Designation* | `Administrador` (o apoderado, representante legal, gerente, director general, consejero delegado) | |
| 14 | **DNI/NIE del representante** | Contact → campo personalizado *DNI* | `12345678Z` | |
| 15 | **Datos del poder** (escritura, notario, fecha, protocolo) | Contact → campo personalizado *Poder* | `Escritura de constitución otorgada ante el notario X el 04/11/2026, n.º de protocolo 000` | |

**Notas:**
- El cargo del punto 13 tiene que ser **una de esas palabras** (sin importar mayúsculas ni tildes): así el sistema sabe que esa persona es la que firma. Está en `config/licitaciones.yaml` → `empresa.designaciones`.
- Si **no hay poder** porque el administrador firma por sí mismo (administrador único), pon en «Poder» el dato de su nombramiento (escritura de constitución o de nombramiento). Si no lo sabes, déjalo en blanco: saldrá como hueco a completar a mano.
- Lo que **no** se guarda aquí, porque las plantillas lo piden a veces pero no es un dato de contacto: la fecha (se completa al firmar), el precio de la oferta (lo fija una persona con «Fijar precio») y las casillas (las marca una persona).

---

## 2. Cómo se carga en ERPNext, paso a paso

### 2.1 La empresa (puntos 1 a 6)
1. En la barra de búsqueda de arriba escribe **Company** y abre la lista.
2. Abre la empresa **101** (la que ya existe). Si hubiera dos, la que presenta las ofertas.
3. Rellena **Company Name**, **Tax ID**, **Phone No**, **Email** y **Country**, y en la sección de registro, **Registration Details**.
4. Pulsa **Save** (Ctrl+S).

### 2.2 La dirección (puntos 7 a 11)
1. Busca **Address** → **New**.
2. **Address Title:** `101 - Sede`. **Address Type:** `Office`.
3. Rellena **Address Line 1**, **City/Town**, **State/Province**, **Postal Code** y **Country**.
4. Abajo, en la tabla **Links**: añade una fila con **Link Document Type = Company** y **Link Name = 101**. *Sin este enlace el sistema no encuentra la dirección.*
5. **Save**.

### 2.3 El contacto del representante (puntos 12 a 15)
1. Busca **Contact** → **New**.
2. **First Name** y **Last Name** del representante; **Designation** (punto 13).
3. En la tabla **Links**: **Link Document Type = Company**, **Link Name = 101**.
4. Los campos **DNI** y **Poder** no vienen de fábrica en ERPNext: hay que crearlos **una vez** (ver 2.4). Después rellénalos aquí.
5. **Save**.

### 2.4 Crear los dos campos personalizados (solo la primera vez)
1. Busca **Customize Form** → en **Doc Type** elige **Contact**.
2. Baja hasta la tabla de campos y pulsa **Add Row** dos veces:

   | Label | Fieldname | Type |
   |-------|-----------|------|
   | `DNI` | `custom_dni` | Data |
   | `Poder` | `custom_poder` | Small Text |

   Solo tienes que escribir la **Label** (`DNI` y `Poder`): ERPNext genera solo el nombre interno (*Fieldname*) añadiendo `custom_`, es decir `custom_dni` y `custom_poder`, que son los que espera `config/licitaciones.yaml` → `empresa.campos`. Si prefieres otros nombres, se cambian ahí y me lo dices.
3. **Update**. Recarga la página del Contacto: ya aparecen.

---

## 3. Comprobar que funciona

1. En Jarvis, abre la ficha de una licitación en estudio y pulsa **«Revisar antes de preparar la oferta»**. La sección «Sociedad que presenta la oferta» debe decir cuántos datos hay disponibles; los que falten se listan con el nombre del campo y dónde completarlo.
2. También se puede ver en el terminal:
   ```
   docker compose exec api python /app/scripts/probar_oferta.py
   ```
3. Cuando no falte ninguno, el siguiente paso es **subir el DEUC** a un chat de Jarvis (agente Administrativo): *«Guarda este documento como DEUC base de 101.cat»*. El DEUC base lleva ya estos datos rellenados y en cada concurso solo se completan los campos propios del concurso.

## 4. Si no los ve el sistema

- **«El departamento “licitaciones” no tiene permitido consultar…»**: al usuario técnico de ERPNext le faltan permisos. Se arregla con
  `python3 scripts/erpnext_roles_cerebro.py --departamento licitaciones` y después
  `docker compose up -d --force-recreate --no-deps api worker beat`.
- **Falta un dato que ya has cargado:** casi siempre es el enlace (**Links**) de la dirección o del contacto con la empresa (apartados 2.2 y 2.3), o el cargo del representante que no es una de las palabras permitidas.
- **No aparece «DNI» o «Poder»:** no se han creado los campos personalizados (2.4) o el nombre interno no coincide con `empresa.campos`.
