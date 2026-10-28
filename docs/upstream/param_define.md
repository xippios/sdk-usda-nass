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

<table>
<tr><td>Column or Header Name</td><td>Max Length</td><td>Definition</td></tr>
<tr><td colspan="3">The "WHAT" (or Commodity) dimension</td></tr>
<tr><td>source_desc (Program)</td><td>60</td><td>Source of data (CENSUS or SURVEY). Census program includes the Census of Ag as well as follow up projects. Survey program includes national, state, and county surveys.</td></tr>
<tr><td>sector_desc (Sector)</td><td>60</td><td>Five high level, broad categories useful to narrow down choices (Crops, Animals &amp; Products, Economics, Demographics, and Environmental).</td></tr>
<tr><td>group_desc (Group)</td><td>80</td><td>Subsets within sector (e.g., under sector = Crops, the groups are Field Crops, Fruit &amp; Tree Nuts, Horticulture, and Vegetables).</td></tr>
<tr><td>commodity_desc (Commodity)</td><td>80</td><td>The primary subject of interest (e.g., CORN, CATTLE, LABOR, TRACTORS, OPERATORS).</td></tr>
<tr><td>class_desc</td><td>180</td><td>Generally a physical attribute (e.g., variety, size, color, gender) of the commodity.</td></tr>
<tr><td>prodn_practice_desc</td><td>180</td><td>A method of production or action taken on the commodity (e.g., IRRIGATED, ORGANIC, ON FEED).</td></tr>
<tr><td>util_practice_desc</td><td>180</td><td>Utilizations (e.g., GRAIN, FROZEN, SLAUGHTER) or marketing channels (e.g., FRESH MARKET, PROCESSING, RETAIL).</td></tr>
<tr><td>statisticcat_desc (Category)</td><td>80</td><td>The aspect of a commodity being measured (e.g., AREA HARVESTED, PRICE RECEIVED, INVENTORY, SALES).</td></tr>
<tr><td>unit_desc</td><td>60</td><td>The unit associated with the statistic category (e.g., ACRES, $ / LB, HEAD, $, OPERATIONS).</td></tr>
<tr><td>short_desc (Data Item)</td><td>512</td><td>A concatenation of six columns: commodity_desc, class_desc, prodn_practice_desc, util_practice_desc, statisticcat_desc, and unit_desc.</td></tr>
<tr><td>domain_desc (Domain)</td><td>256</td><td>Generally another characteristic of operations that produce a particular commodity (e.g., ECONOMIC CLASS, AREA OPERATED, NAICS CLASSIFICATION, SALES). For chemical usage data, the domain describes the type of chemical applied to the commodity. The domain = TOTAL will have no further breakouts; i.e., the data value pertains completely to the short_desc.</td></tr>
<tr><td>domaincat_desc (Domain Category)</td><td>512</td><td>Categories or partitions within a domain (e.g., under domain = Sales, domain categories include $1,000 TO $9,999, $10,000 TO $19,999, etc).</td></tr>
<tr><td colspan="3">The "WHERE" (or Location) dimension</td></tr>
<tr><td>agg_level_desc (Geographic Level)</td><td>40</td><td>Aggregation level or geographic granularity of the data (e.g., State, Ag District, County, Region, Zip Code).</td></tr>
<tr><td>state_ansi</td><td>2</td><td>American National Standards Institute (ANSI) standard 2-digit state codes.</td></tr>
<tr><td>state_fips_code</td><td>2</td><td>NASS 2-digit state codes; include 99 and 98 for US TOTAL and OTHER STATES, respectively; otherwise match ANSI codes.</td></tr>
<tr><td>state_alpha</td><td>2</td><td>State abbreviation, 2-character alpha code.</td></tr>
<tr><td>state_name (State)</td><td>30</td><td>State full name.</td></tr>
<tr><td>asd_code</td><td>2</td><td>NASS defined county groups, unique within a state, 2-digit ag statistics district code.</td></tr>
<tr><td>asd_desc (Ag District)</td><td>60</td><td>Ag statistics district name.</td></tr>
<tr><td>county_ansi</td><td>3</td><td>ANSI standard 3-digit county codes.</td></tr>
<tr><td>county_code</td><td>3</td><td>NASS 3-digit county codes; includes 998 for OTHER (COMBINED) COUNTIES and Alaska county codes; otherwise match ANSI codes.</td></tr>
<tr><td>county_name (County)</td><td>30</td><td>County name.</td></tr>
<tr><td>region_desc (Region)</td><td>80</td><td>NASS defined geographic entities not readily defined by other standard geographic levels. A region can be a less than a state (Sub-State) or a group of states (Multi-State), and may be specific to a commodity.</td></tr>
<tr><td>zip_5 (Zip Code)</td><td>5</td><td>US Postal Service 5-digit zip code.</td></tr>
<tr><td>watershed_code</td><td>8</td><td>US Geological Survey (USGS) 8-digit Hydrologic Unit Code (HUC) for watersheds.</td></tr>
<tr><td>watershed_desc (Watershed)</td><td>120</td><td>Name assigned to the HUC.</td></tr>
<tr><td>congr_district_code</td><td>2</td><td>US Congressional District 2-digit code.</td></tr>
<tr><td>country_code</td><td>4</td><td>US Census Bureau, Foreign Trade Division 4-digit country code, as of April, 2007.</td></tr>
<tr><td>country_name</td><td>60</td><td>Country name.</td></tr>
<tr><td>location_desc</td><td>120</td><td>Full description for the location dimension.</td></tr>
<tr><td colspan="3">The "WHEN" (or Time) dimension</td></tr>
<tr><td>year (Year)</td><td>4</td><td>The numeric year of the data.</td></tr>
<tr><td>freq_desc (Period Type)</td><td>30</td><td>Length of time covered (Annual, Season, Monthly, Weekly, Point in Time). Monthly often covers more than one month. Point in Time is as of a particular day.</td></tr>
<tr><td>begin_code</td><td>2</td><td>If applicable, a 2-digit code corresponding to the beginning of the reference period (e.g., for freq_desc = Monthly, begin_code ranges from 01 (January) to 12 (December)).</td></tr>
<tr><td>end_code</td><td>2</td><td>If applicable, a 2-digit code corresponding to the end of the reference period (e.g., the reference period of Jan thru Mar will have begin_code = 01 and end_code = 03).</td></tr>
<tr><td>reference_period_ desc (Period)</td><td>40</td><td>The specific time frame, within a freq_desc.</td></tr>
<tr><td>week_ending</td><td>10</td><td>Week ending date, used when freq_desc = Weekly.</td></tr>
<tr><td>load_time</td><td>19</td><td>Date and time indicating when record was inserted into Quick Stats database.</td></tr>
<tr><td colspan="3">The Data Value</td></tr>
<tr><td>value</td><td>24</td><td>Published data value or suppression reason code.</td></tr>
<tr><td>CV %</td><td>7</td><td>Coefficient of variation. Available for the 2012 Census of Agriculture only. County-level CVs are generalized.</td></tr>
</table>
