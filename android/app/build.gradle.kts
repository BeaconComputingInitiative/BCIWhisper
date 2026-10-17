plugins {
    id("com.android.application")
}

android {
    namespace = "org.beaconcomputinginitiative.bciwhisper"
    compileSdk = 36

    defaultConfig {
        applicationId = "org.beaconcomputinginitiative.bciwhisper"
        minSdk = 28
        targetSdk = 36
        versionCode = 2
        versionName = "6.0-android-alpha2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
}
