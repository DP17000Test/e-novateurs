# Android Tracker Detection by Static APK Analysis (written by ChatGPT)

## 1. Introduction

Modern Android applications frequently integrate third-party software components known as **Software Development Kits (SDKs)**. SDKs provide reusable functionality such as advertising, analytics, crash reporting, attribution, authentication, payments, or social-media integration.

Some third-party SDKs collect information about the application, the device, or the user. These components are commonly referred to as **trackers** when their functionality includes analytics, advertising, profiling, attribution, or other forms of data collection.

The goal of this project is to identify known tracker SDKs embedded in an Android APK by **static analysis**, without executing the application.

The central question is:

> Which known tracker SDKs are embedded in this APK, and what evidence in the APK identifies them?

The project currently uses two complementary forms of evidence:

1. **Code signatures**: characteristic Java/Kotlin package or class names belonging to a tracker SDK.
2. **Network signatures**: regular expressions describing domains or network-related strings associated with the tracker.

The tracker definitions are obtained from the **Exodus Privacy tracker database**.

---

# 2. What Is a Tracker?

A tracker is a software component capable of collecting information about an application, its user, or the device on which the application runs, and potentially transmitting information to a third party.

Examples of potentially collected information include:

- device identifiers;
- advertising identifiers;
- IP addresses;
- application usage information;
- device characteristics;
- location information;
- advertising interactions;
- crash information;
- diagnostic information;
- account or user identifiers.

The presence of a tracker in an APK must nevertheless be interpreted carefully.

A static analysis can establish that code or other technical markers associated with a tracker are present. It does **not**, by itself, prove that:

- the SDK is initialized;
- the SDK is actually used;
- a network request is made;
- personal data is transmitted;
- a particular user is tracked.

This distinction between **presence** and **runtime activity** is fundamental.

---

# 3. Static Analysis versus Dynamic Analysis

## Static analysis

Static analysis examines the APK without executing it.

Conceptually:

```text
APK
 |
 +-- AndroidManifest.xml
 +-- resources
 +-- assets
 +-- native libraries
 +-- classes.dex
 +-- classes2.dex
 +-- ...
```

The DEX files contain the compiled Java/Kotlin code of the application and its embedded libraries.

Our program searches these DEX files for technical markers associated with known trackers.

## Dynamic analysis

Dynamic analysis executes the application and observes its behaviour:

```text
Application running
 |
 +-- DNS requests
 +-- HTTP/HTTPS requests
 +-- SDK initialization
 +-- identifiers
 +-- permissions used
 +-- data transmitted
```

Dynamic analysis is therefore necessary when the question is:

> "Did this application actually contact this tracker and transmit data?"

Our program instead answers the more limited but highly useful question:

> "Does this APK contain identifiable evidence of this tracker SDK?"

---

# 4. How Android Tracker SDKs Become Part of an APK

Application developers normally do not implement advertising, analytics, crash reporting, etc. themselves. They integrate third-party SDKs.

For example:

```text
Application
 |
 +-- Developer code
 |
 +-- Advertising SDK
 |
 +-- Analytics SDK
 |
 +-- Crash-reporting SDK
 |
 +-- Other libraries
```

When the application is compiled, much of this code becomes part of the APK.

Consequently, the APK contains traces of the SDKs that were integrated into the application.

These traces are what static analysis can exploit.

---

# 5. Loading an APK with Androguard

The application is loaded with:

```python
a, d, dx = AnalyzeAPK(str(apk_path))
```

`AnalyzeAPK()` returns three different objects:

```text
a  -> APK object
d  -> list of DEX objects
dx -> Analysis object
```

This is the standard Androguard structure for APK analysis. `AnalyzeAPK()` returns an `APK`, a list of `DalvikVMFormat`/DEX objects, and an `Analysis` object. 

## 5.1 The `a` object: APK

`a` represents the APK itself.

It provides access to application-level information such as:

```python
package = a.get_package()
app_name = a.get_app_name()
version_name = a.get_androidversion_name()
version_code = a.get_androidversion_code()

permissions = a.get_permissions()
activities = a.get_activities()
services = a.get_services()
receivers = a.get_receivers()
providers = a.get_providers()
apk_files = a.get_files()
```

It can also provide access to the DEX files:

```python
a.get_all_dex()
```

For example, the project uses this information to build the metadata section of the resulting JSON.

## 5.2 The `d` object: DEX files

`d` is a list of DEX objects.

An APK can contain more than one DEX file. This is important because modern applications can be multidex applications.

In our test application, for example:

```text
type(d)       -> list
len(d)        -> 3
type(d[0])    -> androguard.core.dex.DEX
```

Each DEX object provides access to classes, methods, and strings.

This is the object we use for our low-level static inspection.

For network detection, we use the string pools of all DEX files:

```python
def get_dex_strings(apk):

    strings = set()

    for dex in apk.get_all_dex():
        strings.update(dex.get_strings())

    return strings
```

The use of all DEX files is important: examining only `classes.dex` could miss a tracker located in `classes2.dex`, `classes3.dex`, etc.

## 5.3 The `dx` object: Analysis

`dx` is Androguard's higher-level `Analysis` object.

It provides analysis information and cross-references for classes, methods, fields, and strings, and can handle information from multiple DEX objects. 

In this project, we primarily use `d` for direct DEX inspection and `a` for APK metadata. `dx` remains useful for more advanced analysis later.

This distinction is important because the three objects are not interchangeable.

---

# 6. Obtaining the Tracker Definitions

The program does not invent tracker signatures.

Instead, it first needs a database of known trackers.

The **Exodus Privacy tracker database** contains tracker definitions including fields such as:

```json
{
  "name": "Example Tracker",
  "code_signature": "com.example.sdk.",
  "network_signature": "example\\.com",
  "categories": ["Analytics", "Ads"]
}
```

The Exodus API documents a tracker endpoint returning the tracker list, including `name`, `network_signature`, `code_signature`, categories, and other metadata. 

The Exodus project also explains that its static tracker detection is based on tracker-specific code signatures. Its documented process is to obtain an APK, extract the embedded Java classes, and compare those classes with the known tracker signatures. 

## 6.1 The database should be downloaded first

The tracker database should preferably be downloaded **once** and stored locally rather than queried for every APK.

Conceptually:

```text
Exodus tracker database
          |
          v
      local JSON
          |
          v
     APK analyzer
```

This has several advantages:

- much faster analysis of many APKs;
- no need to contact Exodus for every application;
- reproducible analysis;
- the exact tracker database version can be archived;
- easier debugging;
- fewer API requests.

The Exodus API documentation notes that the tracker list does not change frequently and has a relatively strict request limit. 

The Exodus API also requires an API key for API access and documents rate limits. Therefore, for a research project, the database should be treated as a separately downloaded input dataset rather than as a live dependency of every APK analysis. 

---

# 7. Code Signatures

A **code signature** is generally a Java/Kotlin package name or class-name pattern characteristic of a tracker SDK.

For example:

```text
com.appnexus.opensdk.
```

If the DEX files contain:

```text
com.appnexus.opensdk.AdActivity
com.appnexus.opensdk.AdView
com.appnexus.opensdk.MediaType
```

then the AppNexus SDK is strongly indicated.

The basic process is:

```text
DEX classes
     |
     v
Normalize class names
     |
     v
Compare with code_signature
     |
     v
Matching classes
```

The program records the matching classes so that the detection remains auditable.

For example:

```json
{
  "signature": "com.appnexus.opensdk.",
  "matches": [
    "com.appnexus.opensdk.AdActivity",
    "com.appnexus.opensdk.AdView",
    "com.appnexus.opensdk.MediaType"
  ]
}
```

This is preferable to simply reporting:

```text
AppNexus detected
```

because the result contains the actual evidence.

---

# 8. Network Signatures

A tracker may also be identifiable through references to the network infrastructure used by its SDK.

For example:

```text
adnxs\\.com
appnexus\\.com
appnexus\\.net
```

These are regular expressions.

An APK may contain:

```text
https://ib.adnxs.com
https://ib.adnxs.com/
https://ib.adnxs.com/ut/v3
https://ib.adnxs-simple.com/
```

The expression:

```text
adnxs\\.com
```

matches:

```text
ib.adnxs.com
```

The project therefore extracts strings from all DEX files:

```python
def get_dex_strings(apk):

    strings = set()

    for dex in apk.get_all_dex():
        strings.update(dex.get_strings())

    return strings
```

It then applies the regular expressions supplied by Exodus.

For example:

```json
{
  "signature": "adnxs\\.com",
  "string": "https://ib.adnxs.com/ut/v3"
}
```

The complete string is retained because it provides useful evidence for later inspection.

---

# 9. Why Code and Network Signatures Complement Each Other

The two mechanisms answer different questions.

A code signature:

```text
com.appnexus.opensdk.
```

provides evidence that code belonging to the SDK is embedded in the application.

A network signature:

```text
adnxs\\.com
```

provides evidence that the APK contains references to infrastructure associated with that tracker.

Conceptually:

```text
                     APK
                      |
             +--------+--------+
             |                 |
        DEX classes        DEX strings
             |                 |
             v                 v
      Code signatures   Network signatures
             |                 |
             +--------+--------+
                      |
                      v
               Tracker evidence
```

If both mechanisms identify the same SDK, the evidence becomes stronger.

However, the two detections should remain conceptually separate. A package name is not a network endpoint, and a URL is not necessarily proof that the SDK code is active.

---

# 10. Grouping Detections by Signature

The Exodus database can contain several tracker definitions associated with the same technical signature.

For example:

```text
Tracker A
    code_signature = org.acra.

Tracker B
    code_signature = org.acra.
```

If the APK contains:

```text
org.acra.ACRA
org.acra.ErrorReporter
```

the technical evidence is the same.

The program therefore groups trackers by signature rather than creating duplicate evidence.

The JSON structure is:

```json
{
  "trackers": {
    "code": [
      {
        "type": "code",
        "signature": "org.acra.",
        "trackers": [],
        "matches": []
      }
    ],
    "network": [
      {
        "type": "network",
        "signature": "adnxs\\.com",
        "trackers": [],
        "matches": []
      }
    ]
  }
}
```

This distinction is important:

- the **signature** represents technical evidence;
- the **tracker list** represents the Exodus tracker definitions associated with that signature;
- the **matches** contain the actual evidence found in the APK.

---

# 11. What Happens When an Unknown Marker Is Found?

This is an important next step for the project.

Suppose the program encounters something that looks suspicious but does not match any known Exodus signature:

```text
com.somecompany.analytics.
```

or:

```text
https://analytics.somecompany.com/collect
```

The program should **not immediately classify it as a tracker**.

Instead, it should create a separate category such as:

```text
unidentified_markers
```

For example:

```json
{
  "unidentified_markers": {
    "code": [
      "com.somecompany.analytics."
    ],
    "network": [
      "https://analytics.somecompany.com/collect"
    ]
  }
}
```

## 11.1 First step: investigate the marker

For an unknown code marker, investigate:

- the package name;
- the classes below that package;
- the number of classes;
- references to known SDK names;
- embedded documentation;
- copyright notices;
- Maven/Gradle metadata;
- native libraries;
- associated network domains.

For an unknown network marker, investigate:

- whether it is a domain;
- whether it is an API endpoint;
- whether it belongs to the application's own backend;
- whether it belongs to a third-party SDK;
- whether it appears in multiple applications.

## 11.2 Compare across applications

This is particularly useful.

If:

```text
com.somecompany.analytics.
```

appears in 100 unrelated applications, it becomes much more interesting than if it appears in only one application.

A future version of the project could therefore maintain a database of unidentified markers:

```text
Marker
   |
   +-- applications containing it
   +-- versions
   +-- code classes
   +-- network domains
   +-- first seen
   +-- last seen
```

This could become a powerful way of discovering new SDKs.

## 11.3 Search the Exodus database again

The first question should also be:

> Is this actually a tracker that Exodus already knows about but whose signature is incomplete or has changed?

A tracker definition may contain several signatures, or an SDK may have changed package names between versions.

## 11.4 Candidate for a new tracker

If the evidence indicates a genuine third-party tracking SDK that is absent from the current database, it becomes a candidate for further investigation.

Exodus explicitly provides a mechanism for contributing to tracker identification through its ETIP tracker investigation platform. citeturn0search12

Thus the long-term workflow can become:

```text
APK
 |
 +-- known marker
 |      |
 |      +--> Exodus tracker
 |
 +-- unknown marker
        |
        +--> investigate
        |
        +--> correlate across APKs
        |
        +--> identify SDK
        |
        +--> propose/update tracker signature
```

This is potentially one of the most interesting extensions of the project.

---

# 12. Obtaining APKs for Testing

The tracker detector needs APKs to analyse.

We initially used **F-Droid**, which has an important advantage: APKs are directly available from its repositories and the ecosystem is relatively easy to automate.

However, F-Droid has a fundamental limitation for this particular project:

> Its application catalogue is much smaller and has a strong Free/Open Source Software orientation.

That makes it excellent for analysing FOSS applications, but less suitable when the objective is to obtain a large and representative collection of applications containing commercial advertising, analytics, attribution, and other third-party SDKs.

This is exactly why finding a suitable F-Droid application containing a network tracker known to Exodus proved difficult.

---

# 13. Google Play

Google Play is the most important source if the objective is to reproduce the type of analysis performed by Exodus.

The Exodus documentation explicitly describes its static analysis process as downloading the APK from Google Play, extracting the embedded Java classes, and comparing them with tracker code signatures. 

The difficulty is not the APK analysis itself. The difficulty is **obtaining the APK files automatically**.

Google Play is designed primarily for installation through Android/Play services rather than for bulk APK downloading.

In addition, modern Google Play applications may be delivered as multiple APKs or app bundles rather than as one simple universal APK. This can complicate automated extraction and reproducibility.

Therefore:

```text
Google Play
   |
   +-- largest and most representative catalogue
   |
   +-- closest to Exodus' original source
   |
   +-- difficult to automate reliably
   |
   +-- version/build selection can be complicated
```

For a large-scale research dataset, this is the principal obstacle.

---

# 14. Aurora Store

A particularly interesting alternative is **Aurora Store**.

Aurora Store is an alternative client for Google Play. It provides access to applications from the Google Play ecosystem without requiring the normal Play Store application.

For this project, Aurora Store is interesting because it provides a much larger application universe than F-Droid while still making APK acquisition more accessible than interacting directly with the Google Play Store.

Conceptually:

```text
F-Droid
   |
   +-- easy APK access
   +-- open-source focus
   +-- limited catalogue
          |
          v
     Aurora Store
          |
          +-- Google Play catalogue
          +-- APK acquisition
          +-- considerably broader application coverage
```

For experimentation, Aurora Store is therefore worth investigating before attempting to automate Google Play directly.

There are nevertheless practical and legal/technical considerations around downloading and redistributing applications, and the exact availability of versions can vary.

---

# 15. APKMirror and Similar APK Archives

Another practical approach is to use an APK archive such as **APKMirror**.

This has a different advantage:

- APK files are directly downloadable;
- old versions are often available;
- version numbers are visible;
- files can be archived locally;
- it is convenient for reproducible tests.

This was useful for our `willhaben` / AppNexus experiment because we could select a specific application version rather than simply downloading the latest release.

However, an APK archive is not necessarily complete. It should therefore be regarded as a **supplementary source**, not as a replacement for Google Play.

The best approach may ultimately be to use several sources:

```text
                 APK dataset
                     |
       +-------------+-------------+
       |             |             |
    F-Droid       Aurora       APK archives
       |             |             |
       +-------------+-------------+
                     |
                     v
                APK analysis
```

---

# 16. Recommended APK Acquisition Strategy

For the current project, I would recommend the following order.

### 1. F-Droid

Use it when:

- the application is available;
- reproducibility is important;
- the application is FOSS;
- we want an easy and legitimate APK source.

### 2. APK archives

Use them for:

- known test applications;
- historical versions;
- reproducible experiments;
- selecting a specific version associated with an Exodus report.

### 3. Aurora Store

Investigate this as the main source for a larger automated dataset.

It potentially provides the best compromise between:

- catalogue size;
- APK accessibility;
- automation;
- version selection.

### 4. Direct Google Play acquisition

Use this if the project eventually requires:

- maximum catalogue coverage;
- versions that cannot be found elsewhere;
- closer reproduction of Exodus' original acquisition workflow.

The automation is more complicated, and Google Play's delivery model can make APK extraction substantially more difficult than downloading a simple APK file.

---

# 17. Experimental Validation

A particularly important aspect of this project is validation.

We should not assume that because Exodus defines a signature, our detector will necessarily produce the same result.

The validation process should therefore be:

```text
1. Select an application analysed by Exodus
             |
             v
2. Identify its exact version
             |
             v
3. Obtain the same APK
             |
             v
4. Run our static analysis
             |
             v
5. Compare our detected trackers
   with the Exodus report
             |
             v
6. Examine discrepancies
```

The `willhaben` AppNexus example demonstrated this approach.

The APK contained numerous AppNexus-related strings, including:

```text
https://ib.adnxs.com
https://ib.adnxs.com/ut/v3
https://ib.adnxs-simple.com/
```

These provide concrete evidence against the Exodus network signature:

```text
adnxs\\.com
```

The same APK also contained classes under:

```text
com.appnexus.opensdk.
```

This gives us two independent forms of static evidence for the same SDK.

---

# 18. Possible Future Development

Several extensions naturally follow from the current architecture.

## 18.1 Unknown marker detection

Automatically identify frequently occurring third-party namespaces and domains that are not present in the Exodus database.

## 18.2 SDK fingerprint database

Build a local database containing:

```text
SDK
 |
 +-- code signatures
 +-- network signatures
 +-- known classes
 +-- known domains
 +-- versions
 +-- first/last observed
```

## 18.3 Version comparison

Analyse successive versions of an application:

```text
Version 1
    Tracker A

Version 2
    Tracker A
    Tracker B

Version 3
    Tracker B
```

This would make it possible to detect the introduction or removal of SDKs.

## 18.4 Confidence scoring

Instead of a binary result, assign evidence levels:

```text
Code signature only
        -> medium confidence

Network signature only
        -> medium confidence

Code + network signatures
        -> stronger evidence

Multiple independent markers
        -> strongest evidence
```

The score should remain an indicator of **static evidence**, not a probability that tracking actually occurred.

## 18.5 Dynamic validation

The final stage could combine static and dynamic analysis:

```text
Static analysis
      |
      v
Identify candidate SDKs
      |
      v
Run application
      |
      v
Observe network traffic
      |
      v
Compare predicted and observed trackers
```

This would provide a much stronger picture of actual runtime behaviour.

---

# 19. Conclusion

The project is based on a relatively simple but powerful idea:

> **A tracker SDK leaves technical fingerprints inside an APK.**

The Exodus database provides known fingerprints in the form of code and network signatures.

Androguard gives us access to the APK, its DEX files, classes, methods, and strings.

The program connects these two sources:

```text
Exodus tracker database
          |
          | signatures
          v
       Analyzer
          ^
          | APK evidence
          |
         APK
```

The resulting JSON does not merely say that a tracker was found. It can preserve the technical evidence that led to the detection.

This makes the system useful not only for analysing individual applications but also for building a reproducible dataset of tracker presence across applications and versions.

The next major research direction is to move beyond known trackers: identify **unknown but recurring code and network markers**, investigate them, determine whether they correspond to third-party SDKs, and potentially feed newly identified signatures back into a tracker knowledge base.

That would turn the project from a simple tracker detector into a system capable of **discovering and monitoring the evolution of tracking SDKs in the Android ecosystem**.
