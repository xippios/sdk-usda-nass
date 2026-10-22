# Quick Stats Column Definitions

Snapshot of <https://quickstats.nass.usda.gov/param_define>, fetched 2026-10-22 by /refresh-upstream. Do not edit by hand.

---

**Quick Stats Column Definitions**

2/19/2013

The table below lists the columns
found on the Quick Stats search page and in Quick Stats data products.

1)      All
columns shown are included in output from:

a)      The [search page](https://quickstats.nass.usda.gov/) results "Spreadsheet" option

b)      API calls
(also, the same columns are available for API input)

c)       Tab
delimited ASCII text files downloadable from the [Data Set Download](https://www.nass.usda.gov/datasets/)

2)      The
column or header names shown below in parentheses (e.g., (Program), (Sector),
etc.) are the corresponding headers found on the [search page](https://quickstats.nass.usda.gov/).

|  |  |  |
| --- | --- | --- |
| **Column or Header Name** | **Max Length** | **Definition** |
| The "WHAT" (or Commodity) dimension | | |
| source_desc  (Program) | 60 | Source of data (CENSUS or SURVEY). Census program includes the Census of Ag as well as follow up projects. Survey program includes national, state, and county surveys. |
| sector_desc  (Sector) | 60 | Five high level, broad categories useful to narrow down choices (Crops, Animals & Products, Economics, Demographics, and Environmental). |
| group_desc  (Group) | 80 | Subsets within sector (e.g., under sector = Crops, the groups are Field Crops, Fruit & Tree Nuts, Horticulture, and Vegetables). |
| commodity_desc  (Commodity) | 80 | The primary subject of interest (e.g., CORN, CATTLE, LABOR, TRACTORS, OPERATORS). |
| class_desc | 180 | Generally a physical attribute (e.g., variety, size, color, gender) of the commodity. |
| prodn_practice_desc | 180 | A method of production or action taken on the commodity (e.g., IRRIGATED, ORGANIC, ON FEED). |
| util_practice_desc | 180 | Utilizations (e.g., GRAIN, FROZEN, SLAUGHTER) or marketing channels (e.g., FRESH MARKET, PROCESSING, RETAIL). |
| statisticcat_desc  (Category) | 80 | The aspect of a commodity being measured (e.g., AREA HARVESTED, PRICE RECEIVED, INVENTORY, SALES). |
| unit_desc | 60 | The unit associated with the statistic category (e.g., ACRES, $ / LB, HEAD, $, OPERATIONS). |
| short_desc  (Data Item) | 512 | A concatenation of six columns: commodity_desc, class_desc, prodn_practice_desc, util_practice_desc, statisticcat_desc, and unit_desc. |
| domain_desc  (Domain) | 256 | Generally another characteristic of operations that produce a particular commodity (e.g., ECONOMIC CLASS, AREA OPERATED, NAICS CLASSIFICATION, SALES). For chemical usage data, the domain describes the type of chemical applied to the commodity. The domain = TOTAL will have no further breakouts; i.e., the data value pertains completely to the short_desc. |
| domaincat_desc (Domain Category) | 512 | Categories or partitions within a domain (e.g., under domain = Sales, domain categories include $1,000 TO $9,999, $10,000 TO $19,999, etc). |
| The "WHERE" (or Location) dimension | | |
| agg_level_desc  (Geographic Level) | 40 | Aggregation level or geographic granularity of the data (e.g., State, Ag District, County, Region, Zip Code). |
| state_ansi | 2 | American National Standards Institute (ANSI) standard 2-digit state codes. |
| state_fips_code | 2 | NASS 2-digit state codes; include 99 and 98 for US TOTAL and OTHER STATES, respectively; otherwise match ANSI codes. |
| state_alpha | 2 | State abbreviation, 2-character alpha code. |
| state_name  (State) | 30 | State full name. |
| asd_code | 2 | NASS defined county groups, unique within a state, 2-digit ag statistics district code. |
| asd_desc  (Ag District) | 60 | Ag statistics district name. |
| county_ansi | 3 | ANSI standard 3-digit county codes. |
| county_code | 3 | NASS 3-digit county codes; includes 998 for OTHER (COMBINED) COUNTIES and Alaska county codes; otherwise match ANSI codes. |
| county_name  (County) | 30 | County name. |
| region_desc  (Region) | 80 | NASS defined geographic entities not readily defined by other standard geographic levels. A region can be a less than a state (Sub-State) or a group of states (Multi-State), and may be specific to a commodity. |
| zip_5  (Zip Code) | 5 | US Postal Service 5-digit zip code. |
| watershed_code | 8 | US Geological Survey (USGS) 8-digit Hydrologic Unit Code (HUC) for watersheds. |
| watershed_desc  (Watershed) | 120 | Name assigned to the HUC. |
| congr_district_code | 2 | US Congressional District 2-digit code. |
| country_code | 4 | US Census Bureau, Foreign Trade Division 4-digit country code, as of April, 2007. |
| country_name | 60 | Country name. |
| location_desc | 120 | Full description for the location dimension. |
| The "WHEN" (or Time) dimension | | |
| year  (Year) | 4 | The numeric year of the data. |
| freq_desc  (Period Type) | 30 | Length of time covered (Annual, Season, Monthly, Weekly, Point in Time). Monthly often covers more than one month. Point in Time is as of a particular day. |
| begin_code | 2 | If applicable, a 2-digit code corresponding to the beginning of the reference period (e.g., for freq_desc = Monthly, begin_code ranges from 01 (January) to 12 (December)). |
| end_code | 2 | If applicable, a 2-digit code corresponding to the end of the reference period (e.g., the reference period of Jan thru Mar will have begin_code = 01 and end_code = 03). |
| reference_period_  desc (Period) | 40 | The specific time frame, within a freq_desc. |
| week_ending | 10 | Week ending date, used when freq_desc = Weekly. |
| load_time | 19 | Date and time indicating when record was inserted into Quick Stats database. |
| The Data Value | | |
| value | 24 | Published data value or suppression reason code. |
| CV % | 7 | Coefficient of variation. Available for the 2012 Census of Agriculture only. County-level CVs are generalized. |
