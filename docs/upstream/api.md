# Quick Stats API

Snapshot of <https://quickstats.nass.usda.gov/api>, fetched 2026-10-22 by /refresh-upstream. Do not edit by hand.

---

# QuickStats API

Introduction

Terms of Service

Usage

Request API Key

The National Agricultural Statistics Service (NASS) offers Quick Stats, an on-line database containing official published aggregate estimates related to U.S. agricultural production. NASS develops these estimates from data collected through:

1. 1) hundreds of sample surveys conducted each year covering virtually every aspect of U.S. agriculture
2. 2) the Census of Agriculture conducted every five years providing state- and county-level aggregates

The Quick Stats application programming interface (API) provides direct access to the statistical information in the Quick Stats database. We invite developers to use this API and to give us feedback so we can continue to improve it.

#### About the Quick Stats API

To use the Quick Stats API, you must first agree to the NASS Terms of Service and obtain an API key In registering for the key, you must provide a valid email address. You will have the option to request future email updates about the Quick Stats API.

Once you request the API key, we will email it and you can proceed immediately. Use the key in all future data requests as well.
To call the Quick Stats API, you may use either of the following:

- any language that supports HTTP GET request such as PHP, PERL, etc...
- JSON with padding or JSONP

Your request will return a maximum of 50,000 data records. You can determine the returned record account before you execute the Quick Stats API call using the GET /api/get_counts function. If your request will return more than the maximum limit of 50,000 data records, you can do either of the following:

- Change the filtering criteria (the API input parameters and their values) to generate a smaller number of responses
- Download [the files](https://www.nass.usda.gov/datasets/) containing larger amounts of data extracted from the Quick Stats database.

**Using QuickStats API**

QuickStats API requests utilize input parameters based on the concept of What, Where and When.

- What parameters refer to a commodity, data item or subject area.
- Where parameters refer to a location or geographic level such as the entire United States, state, county, district, or ZIP code.
- When parameters refer to a time such as year and frequency such as monthly.

**QuickStats API Input**

The QuickStats API has three resources you can use to retrieve NASS published estimate data and properties, in combination with the "WHAT" and/or "WHERE" and/or "WHEN" parameters you specify. See Parameter Definitions and Operators for definitions and types. If you have not already
 obtained an API key, do so now before proceeding.

Here are the resources, their URIs and examples:

1. 1) GET  /api/api_GET: accepts a combination of "WHAT" and/or "WHERE and/or "WHEN" parameters and return maximum of 50K records

   https://quickstats.nass.usda.gov/api/api_GET/?key=api key&{parameter ... parameter}&format={json | csv | xml}&callback={function name}

   ***Note:*** callback parameter needs only for using JSONP

   Example  of /api/api_GET request and its output.

   Close(X)

   **Example of GET request corn of VA since 2012**

   GET

   `https://quickstats.nass.usda.gov/api/api_GET/?key=api key&commodity_desc=CORN&year__GE=2012&state_alpha=VA&format=JSON
   https://quickstats.nass.usda.gov/api/api_GET/?key=api key&commodity_desc=CORN&year__GE=2012&state_alpha=VA&format=XML
   https://quickstats.nass.usda.gov/api/api_GET/?key=api key&commodity_desc=CORN&year__GE=2012&state_alpha=VA&format=CSV`

   **Example Output:**

   JSON

   {data:[{"week_ending":"","state_name":"VIRGINIA","country_code":"9000","begin_code":"00", "sector_desc":"CROPS","zip_5":"","county_ansi":"","state_alpha":"VA","util_practice_desc":"ALL UTILIZATION PRACTICES","domain_desc":"TOTAL","asd_desc":"","freq_desc":"ANNUAL","prodn_practice_desc":"ALL PRODUCTION PRACTICES","end_code":"00","short_desc":"CORN - ACRES PLANTED","country_name":"UNITED STATES","Value":"510,000","reference_period_desc":"YEAR","source_desc":"SURVEY","group_desc":"FIELD CROPS","asd_code":"","agg_level_desc":"STATE","Class_desc":"ALL CLASSES","county_name":"","region_desc":"","watershed_desc":"","state_ansi":"51","congr_district_code":"","domaincat_desc":"NOT SPECIFIED","watershed_code":"00000000","commodity_desc":"CORN","unit_desc":"ACRES","load_time":"2012-10-11 11:26:13","statisticcat_desc":"AREA PLANTED","year":"2012"}]}

   CSV

   "source_desc","sector_desc","group_desc","commodity_desc","class_desc","util_practice_desc","prodn_practice_desc","statisticcat_desc","unit_desc","short_desc","domain_desc","domaincat_desc","agg_level_desc","state_ansi","state_alpha","state_name","asd_code","asd_desc","county_ansi","county_name","region_desc","zip_5","watershed_code","watershed_desc","congr_district_code","country_code","country_name","year","freq_desc","begin_code","end_code","reference_period_desc","week_ending","load_time","Value"
   "SURVEY","CROPS","FIELD CROPS","CORN","ALL CLASSES","ALL UTILIZATION PRACTICES","ALL PRODUCTION PRACTICES","AREA PLANTED","ACRES","CORN - ACRES PLANTED","TOTAL","NOT SPECIFIED","STATE","51","VA","VIRGINIA","","","","","","","00000000","","","9000","UNITED STATES","2012","ANNUAL","00","00","YEAR","","2012-10-11 11:26:13","510,000"
   "SURVEY","CROPS","FIELD CROPS","CORN","ALL CLASSES","ALL UTILIZATION PRACTICES","ALL PRODUCTION PRACTICES","AREA PLANTED","ACRES","CORN - ACRES PLANTED","TOTAL","NOT SPECIFIED","STATE","51","VA","VIRGINIA","","","","","","","00000000","","","9000","UNITED STATES","2012","ANNUAL","00","00","YEAR - MAR FORECAST","","2012-04-24 12:56:11","500,000"

   XML

   `<arrayref memory_address="0x6b53698">
   <item key="0">
   <hashref memory_address="0x70ee778">
   <item key="class_desc">ALL CLASSES</item>
   <item key="commodity_desc">CORN</item>
   <item key="group_desc">FIELD CROPS</item>
   <item key="source_desc">SURVEY</item>
   <item key="sector_desc">CROPS</item>
   <item key="Value">510,000</item>
   <item key="agg_level_desc">STATE</item>
   <item key="asd_code"/>
   <item key="asd_desc"/>
   <item key="begin_code">00</item>
   <item key="congr_district_code"/>
   <item key="country_code">9000</item>
   <item key="country_name">UNITED STATES</item>
   <item key="county_ansi"/>
   <item key="county_name"/>
   <item key="domain_desc">TOTAL</item>
   <item key="domaincat_desc">NOT SPECIFIED</item>
   <item key="end_code">00</item>
   <item key="freq_desc">ANNUAL</item>
   <item key="load_time">2012-10-11 11:26:13</item>
   <item key="prodn_practice_desc">ALL PRODUCTION PRACTICES</item>
   <item key="reference_period_desc">YEAR</item>
   <item key="region_desc"/>
   <item key="short_desc">CORN - ACRES PLANTED</item>
   <item key="state_alpha">VA</item>
   <item key="state_ansi">51</item>
   <item key="state_name">VIRGINIA</item>
   <item key="statisticcat_desc">AREA PLANTED</item>
   <item key="unit_desc">ACRES</item>
   <item key="util_practice_desc">ALL UTILIZATION PRACTICES</item>
   <item key="watershed_code">00000000</item>
   <item key="watershed_desc"/>
   <item key="week_ending"/>
   <item key="year">2012</item>
   <item key="zip_5"/>
   </hashref>
   </item>
   </arrayref>`
2. 2) GET  /api/get_param_values: accepts a parameter name and return all possible values of the parameter.

   https://quickstats.nass.usda.gov/api/get_param_values/?key=api key&param={parameter}

   Example of get values of sector_desc parameter:
    GET     https://quickstats.nass.usda.gov/api/get_param_values/?key=api key&param=sector_desc

   Return {"sector_desc":["ANIMALS & PRODUCTS","CROPS","DEMOGRAPHICS","ECONOMICS","ENVIRONMENTAL"]}
3. 3) GET  /api/get_counts: accepts a combination of "WHAT" and/or "WHERE and/or "WHEN" parameters and return the number of counts

   https://quickstats.nass.usda.gov/api/get_counts/?key=api key&{parameter ... parameter}

   Example of get number of rows of corn in VA since 2012:
    GET     https://quickstats.nass.usda.gov/api/get_counts/?key=api key&commodity_desc=CORN&year__GE=2012&state_alpha=VA

   Return {"count":"27"}

**QuickStats API Output**

- A request will return the published estimate for a given set of call parameters.
- The api_GET resource supports three different output formats: JSON(default), XML or CSV.
- The output format is identified by using the format parameter in the API request

**Error messages**

Error messages that the API will return:

- "exceeds limit = 50000" - The request would return more than 50,000 records/rows.
- "bad request - invalid query" - There is an error in the query string, such as wrong parameter name or value.
- "bad request - unsupport media type" - The request format parameter is not JSON or CSV or XML.
- "unauthorized" - There is no key or invalid key parameter.

**QuickStats Parameter Definitions and Operators**

Listed below are the
parameters
available in QuickStats, along with their definitions, to use in defining your query, as well as the
operators
to use within the parameters in the query string. The parameters correspond to the categories on the QuickStats application(e.g., [Program], [Sector], etc.)

Close(X)

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

Close(X)

### Operators

These operators can be used within parameters in the query string:
__LE = <=
__LT = <
__GT = >
__GE = >=
__LIKE = like
__NOT_LIKE = not like
__NE = not equal

Example of URI of get published statistics for corn in Virginia for years **greater than or equal** to 2010

https://quickstats.nass.usda.gov/api/api_GET/?key=api key&commodity_desc=CORN&**year__GE=2010**&state_alpha=VA

To obtain an API key, please submit the form below then you will receive the key in your email.

**NASS API Terms of Service**

The National Agricultural Statistics Service (NASS), a sub-agency of the United States Department of Agriculture (USDA), collectively called "our" or "we," offers the general public, collectively referred to as "you," some of our public data in machine readable format via an Application Programming Interface (API). This service is offered subject to your acceptance of the terms and conditions contained herein as well as any relevant sections of the [USDA Web Privacy Policy](https://www.usda.gov/wps/portal/usda/usdahome?navtype=FT&navid=PRIVACY_POLICY) (collectively, the Agreement)

**Scope**

All of the content, documentation, code and related materials made available to you through the NASS API are subject to these terms. Access to or use of the NASS API or its content constitutes acceptance of this Agreement.

**Use**

You may use the NASS API to develop a service to search, display, analyze, retrieve, view and otherwise 'get' information from NASS data

**Attribution**

All services which utilize or access the API should display the following notice prominently within the application: "This product uses the NASS API but is not endorsed or certified by NASS." You may use the NASS name in order to identify the source of API content, subject to these rules. You may not use the NASS name to imply endorsement of any product, service, or entity (not-for-profit, commercial or otherwise).

**Modification or False Representation of Content**

You may not modify or falsely represent content accessed through the NASS API and still claim the source is NASS.

 **Right to Limit**

Your use of the NASS API may be subject to certain limitations on access, calls, or use as set forth within this Agreement or otherwise provided by NASS. If we reasonably believe that you have attempted to exceed or circumvent these limits, your ability to use the NASS API may be permanently or temporarily blocked. We may monitor your use of the API to improve the service or to insure compliance with this Agreement.

 **Service Termination**

If you wish to terminate this Agreement, you may do so by not using the NASS API. We reserve the right (though not the obligation) to (1) refuse to provide the NASS API to you, if it is our opinion that your use violates any of our policies, or (2) terminate or deny you access to and use of all or part of the NASS API at any time for any other reason at our sole discretion. All provisions of this Agreement which by their nature should survive termination shall survive termination including, without limitation, warranty disclaimers, indemnity, and limitations of liability.

**Changes**

We reserve the right, at our sole discretion, to modify or replace this Agreement, in whole or in part. Your continued use of or access to the NASS API following posting of any changes to this Agreement constitutes acceptance of those modified terms. We may, in the future, modify or offer new services and/or features through the NASS API. Such new features and/or services shall be subject to the terms and conditions of this Agreement.

**Disclaimer of Warranties**

The NASS API is provided âas isâ and on an "as-available" basis. We hereby disclaim all warranties of any kind, express or implied, including without limitation the warranties of merchantability, fitness for a particular purpose, and non-infringement. We make no warranty that the NASS API will be error-free, that the underlying data will be error-free, or that access thereto will be continuous or uninterrupted.

**Limitations on Liability**

In no event will we be liable with respect to any subject matter of this Agreement under any contract, negligence, strict liability or other legal or equitable theory for (1) any special, incidental, or consequential damages; (2) the cost of procurement of substitute products or services; or (3) interruption of use or loss or corruption of data.

**General Representations**

You hereby warrant that (1) your use of the NASS API will be in strict accordance with the USDA Privacy Policy, this Agreement, and all applicable laws and regulations, and (2) your use of the NASS API will not infringe or misappropriate the intellectual property rights of any third party.

**Indemnification**

You agree to indemnify and hold harmless NASS, its contractors, employees, agents, and the like from and against any and all claims and expenses, including attorney's fees, arising out of your use of the NASS API, including but not limited to violation of this Agreement.

 **Miscellaneous**

This Agreement constitutes the entire Agreement between NASS and you concerning the subject matter hereof, and may only be modified by the posting of a revised version on this page by NASS.

**Disputes**

Any disputes arising out of this Agreement and access to or use of the NASS API shall be governed by federal law.

 **No Waiver of rights**

Our failure to exercise or enforce any right or provision of this Agreement shall not constitute waiver of such right or provision.
