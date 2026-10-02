Demand-Driven Medicine Expiry Management System Using FEFO

Author: Kimuruae Sururu Edwin
Admission No.	166317
Class	BBIT 4C
Supervisor	Dr. Mary Njeri Ngaruiya
Institution: School of Computing & Engineering Sciences, Strathmore University
Academic Year: 2026

About:
A web-based, demand-driven medicine inventory system built for Kenyan Level-4 hospitals, 
using First-Expiry, First-Out (FEFO) dispensing logic and a 3-month moving average demand forecast to reduce pharmaceutical expiry and waste.
Final-year Information Systems project — BBIT 4C, School of Computing & Engineering Sciences, Strathmore University.

Overview:
Medicine expiry in Kenyan healthcare facilities remains a persistent challenge: poor inventory visibility, 
manual stock rotation, and procurement that is disconnected from actual consumption all contribute to pharmaceutical 
wastage estimated at KSh 9.5 billion annually, with an expiry rate roughly six times the global average.
This project is a working prototype of a system that addresses that problem directly. It uses synthetic inventory data 
(generated via Python's Faker library) to demonstrate how a web-based platform can: Enforce FEFO-based dispensing 
automatically, rather than relying on manual stock inspection. Generate real-time expiry alerts at 90, 60, and 30 days 
before a batch expires. Forecast demand using a 3-month moving average of dispensing history. Trigger procurement 
recommendations when projected stock falls below a 30-day safety threshold.
The system is being developed using the Prototyping methodology with Object-Oriented Analysis and Design (OOAD), as 
detailed in the accompanying project proposal.

Problem Statement
Healthcare facilities in Kenya largely rely on manual or fragmented inventory systems that provide no real-time visibility into approaching expiry dates. The link between central medicine supply and facility-level demand is weak, resulting in hospitals receiving batches with short shelf lives or quantities that exceed realistic consumption. This system demonstrates how an integrated, demand-driven approach — FEFO dispensing plus forecasting plus procurement alerts in a single platform — can close that gap.