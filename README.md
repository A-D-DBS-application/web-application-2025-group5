[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/DxqGQVx4)
## FairSplit+  
Web Application Development Project 2025 – Group 5

FairSplit+ is een webapplicatie waarmee vriendengroepen eenvoudig gezamenlijke uitgaven kunnen beheren tijdens reizen, weekends, activiteiten of evenementen.  
De app ondersteunt het aanmaken van tijdelijke groepen, het toevoegen van kosten, automatische saldoberekening, afbetalingen via een knop en een automatische verdeling van de app-fee.

## Demo
Link naar de demo: https://ugentbe-my.sharepoint.com/:p:/g/personal/nicolas_bruijlants_ugent_be/IQA0ZUYJok4zS7JSB-U9nSG3AT1cKRvCeVVvmzAznBfQ-AA?e=8brL6b

## Presentatie
Link naar de presentatie (Google Drive): 
https://docs.google.com/presentation/d/1SugZQhHqAE7xcgoYFEgJmEHtwWBIlhy9/edit?usp=sharing&ouid=112093568013996913032&rtpof=true&sd=true


Functionaliteiten

## Groepen & leden
- Aanmaken van tijdelijke groepen met een start- en einddatum  
- Uitnodigen van leden via een gedeelde whatsapp link  
- Automatische sluiting van groepen na de einddatum (uitgaven toevoegen wordt niet meer mogelijk) 

## Uitgavenbeheer
- Toevoegen van uitgaven met beschrijving en totale kost   
- Automatische verdeling van kosten per gebruiker  
- Mogelijkheid tot equal split of handmatig andere bedragen over leden

## Berekeningen & betalingen
- Automatische berekening van wie hoeveel moet betalen  
- Optimalisatie van het aantal transacties (=slim algoritme)
- Ondersteuning voor afbetalingen via knop "ik heb betaald"  
- Opslag van uitgevoerde betalingen in de database  

## Rapportage
- Overzichtelijk saldo per persoon  
- Eindoverzicht van alle uitgaven  
- Exportmogelijkheden (PDF-document)


## Documentatie

### User Stories  
Te vinden in:  
`docs/user_stories/`
Opmerking: In samenspraak met assistent Derave en de partner is beslist om AI-functionaliteiten, zoals spraakmogelijkheden en het uitlezen van bedragen uit bonnetjes, te classificeren als een could in plaats van een must.

### DDL / databank
Te vinden in:  
`docs/ddl/`

### ERD-model
Te vinden in:  
`docs/erd/`
Opmerking: Voor onze applicatie maken wij geen gebruik van een ORM. Dit hebben wij besproken met assistent Derave om na te gaan of dit alsnog aangepast moest worden. Hij heeft duidelijk aangegeven dat dit niet nodig is.  
De bijbehorende e-mailcommunicatie is terug te vinden onder:
`docs/mailORM/`

### UI-screenshots
Te vinden in:  
`docs/ui/`
Opmerking: deze UI werd gemaakt met behulp van Lovable. Voor onze eigen UI is er gekozen voor een volledig custom design. Van daar dat dit een redelijk groot bestand is. 

### Database backup
Te vinden in:  
`docs/backup/`

### FEEDBACKMOMENTEN
Links hieronder:
Opmerking: 1 feedback vond plaats via mail. De externe partner heeft het zeer druk gehad dit semester. 
De feedback via mail kunnen jullie raadplegen onder:
   `docs/feedbackmail/`

- Link videofeedback 1: https://drive.google.com/file/d/18GVGtQyVDlZQXwmkKhk9-Z1LCEiNyXLe/view
- Link videofeedback 2: https://drive.google.com/file/d/18Nwji8h_Ud8JTCY79aqU4V9VTB3dq_e5/view

## Teamleden

Victor De Greef - Algemeen manager (alle taken)
Heike Van de Walle - Databasemanager (hoofdzakelijk supabase)
Louise Callebaut - UI-designer (hoofdzakelijk html en style)
Milan Dever - Programmeur (hoofdzakelijk routes en models)
Nicolas Bruijlants - Programmeur (hoofdzakelijk routes en models)

## Mogelijke uitbreidingen
- AI-gestuurde bonnenscanner  
- Automatische categorisatie van kosten  
- Groepsstatistieken & grafieken  
- Notificaties bij betalingen en verlopen van de groep
