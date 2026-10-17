plugins {
    id("com.android.application")
}

android {
    namespace = "org.beaconcomputinginitiative.bciwhisper"
    compileSdk = 37

    defaultConfig {
        applicationId = "org.beaconcomputinginitiative.bciwhisper"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "6.0-android-alpha1"
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
