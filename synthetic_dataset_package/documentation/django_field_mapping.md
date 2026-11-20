1\. Medicines

File: datasets/medicines.csv



Target: 100 records.

Column	Data type	Description

medicine\_id	String	Synthetic identifier, e.g. MED001

name	String	Medicine name

medicine\_name	String	Same value as name

generic\_name	String	Generic medicine name

category	String	Therapeutic category

dosage\_form	String	Tablet, capsule, syrup, injection, etc.

reorder\_level	Integer	Reorder threshold

safety\_stock\_days	Integer	Safety stock coverage

is\_active	Boolean	Whether medicine is active



2\. Suppliers

File: datasets/suppliers.csv



Target: 15 fictional suppliers.

Column	Data type	Description

supplier\_id	String	Synthetic identifier, e.g. SUP001

supplier\_name	String	Unique supplier name

name	String	Same as supplier\_name

contact\_person	String	Fictional contact

email	String	Fictional email

phone\_number	String	Supplier contact

phone	String	Same as phone\_number

address	String	Fictional Kenyan address

is\_active	Boolean	Supplier status



3\. Medicine batches

File: datasets/medicine\_batches.csv



Target: Approximately 500 initial/historical batches, plus batches generated through goods receipts.

Column	Data type	Description

batch\_id	String	Synthetic batch identifier

medicine\_id	String	References medicines.csv

batch\_number	String	Batch number

quantity\_received	Integer	Original received quantity

quantity\_available	Integer	Remaining quantity at snapshot

received\_date	Date	Date received

expiry\_date	Date	Expiry date

storage\_location	String	Storage location

status	String	Batch status



The batch dataset must reconcile with historical dispensing and other stock movements.

4\. Dispensing transactions

File: datasets/dispensing\_transactions.csv

Column	Data type	Description

transaction\_id	String	Synthetic transaction identifier

medicine\_id	String	Medicine reference

batch\_id	String	Batch reference

quantity\_dispensed	Integer	Quantity dispensed

dispensed\_date	DateTime	Historical dispensing timestamp

dispensed\_at	DateTime	Same timestamp as dispensed\_date

is\_override	Boolean	Whether FEFO was overridden

patient\_identifier	String	Synthetic, non-identifying reference

notes	String	Transaction explanation



dispensed\_by will remain empty because we are not generating synthetic user accounts.

5\. Demand forecasts: evaluation

File: datasets/demand\_forecasts\_evaluation.csv



Target: 600 records.

Column	Data type	Description

forecast\_id	String	Synthetic forecast identifier

medicine\_id	String	Medicine reference

forecast\_period\_start	Date	Forecast month start

forecast\_period\_end	Date	Forecast month end

forecasted\_demand\_quantity	Integer	Predicted demand

moving\_avg\_3month	Integer	Three-month moving average

forecast\_method	String	MOVING\_AVERAGE

history\_start\_date	Date	Beginning of historical window

history\_end\_date	Date	End of historical window

historical\_transaction\_count	Integer	Historical transaction count

confidence\_score	Decimal	Documented confidence interpretation

actual\_demand\_quantity	Integer	Actual evaluation demand

absolute\_error	Integer	Absolute forecast error



generated\_at is automatically populated by Django.



Important: We will not invent statistical confidence scores. Since your model requires this field, we will use its documented default of 0.00 to indicate that confidence has not been calibrated, rather than presenting an unsupported probability.

6\. Demand forecasts: November 2026

File: datasets/demand\_forecasts\_november\_2026.csv



Target: 100 records.



Use the same forecast columns, but:

\- Forecast period: 1–30 November 2026.

\- Historical window: 1 August–31 October 2026.

\- actual\_demand\_quantity and absolute\_error: empty because November actual demand is not yet available.

7\. Procurement recommendations

File: datasets/procurement\_recommendations.csv

Column	Data type	Description

recommendation\_id	String	Synthetic identifier

medicine\_id	String	Medicine reference

forecast\_id	String	Optional forecast reference

recommended\_quantity	Integer	Recommended procurement quantity

urgency\_level	String	LOW, MEDIUM or HIGH

reasoning	String	Explanation

status	String	Pending, Approved, Rejected, Actioned or Cancelled

is\_actioned	Boolean	Whether actioned



raised\_by, reviewed\_by, created\_at and updated\_at will be handled according to their model definitions.

8\. Purchase orders

File: datasets/purchase\_orders.csv

Column	Data type	Description

purchase\_order\_id	String	Synthetic identifier

medicine\_id	String	Medicine reference

supplier\_id	String	Supplier reference

recommendation\_id	String	Optional, unique recommendation reference

quantity\_ordered	Integer	Ordered quantity

total\_amount	Decimal	Total order amount

total\_cost	Decimal	Total cost

status	String	Valid PurchaseOrder status



Use only the exact status values from your model:

\- PENDING

\- Pending Admin Review

\- Approved

\- Rejected

\- Placed with Supplier

9\. Goods receipts

File: datasets/goods\_receipts.csv

Column	Data type	Description

goods\_receipt\_id	String	Synthetic identifier

purchase\_order\_id	String	Purchase order reference

delivery\_date	Date	Delivery date

delivery\_reference	String	Delivery reference

notes	String	Receipt notes



received\_by and received\_at are handled separately.

10\. Goods receipt items

File: datasets/goods\_receipt\_items.csv

Column	Data type	Description

receipt\_item\_id	String	Synthetic identifier

goods\_receipt\_id	String	Receipt reference

batch\_id	String	Optional medicine batch reference

batch\_number	String	Batch number

quantity\_received	Integer	Received quantity

expiry\_date	Date	Batch expiry

storage\_location	String	Storage location

inspection\_status	String	Pending, Accepted, Rejected or Quarantined

inspection\_notes	String	Inspection explanation



The medicine\_batch relationship must be unique when populated because it is a OneToOne relationship.



Stage 3: Define the dataset relationships

The following is the intended relationship structure.

Dataset relationship map

Medicine



100 master records





MedicineBatch



Multiple batches per medicine





DispensingTransaction



Batch-level dispensing history





DemandForecast



Historical evaluation and forward forecast





ProcurementRecommendation





PurchaseOrder



Linked to one supplier and optionally one recommendation





GoodsReceipt





GoodsReceiptItem



Optionally linked to a MedicineBatch



Supplier is linked to PurchaseOrder, not directly to MedicineBatch.